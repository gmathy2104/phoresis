"""
Image views for Gel Analyzer.

Provides:
- image_list_view: List all images with filtering
- image_upload_view: Upload new images
- image_detail_view: View image details with analyses
- image_delete_view: Delete an image
"""

import contextlib
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from gel_analyzer.forms.image_forms import GelImageUploadForm
from gel_analyzer.models import GelAnalysis, GelImage
from gel_analyzer.services.file_handler import GelFileHandler
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


@login_required
def image_list_view(request):
    """
    List all gel images with filtering and search.

    Supports:
    - Gel type filter
    - Search by filename/description
    - Dual view (cards/table)
    """
    # Get filter parameters
    gel_type_filter = request.GET.get("gel_type", "")
    analyzed_filter = request.GET.get("analyzed", "")
    search_query = request.GET.get("q", "")
    view_mode = request.GET.get("view", "cards")
    sort_by = request.GET.get("sort", "-uploaded_at")

    # Validate sort parameter
    valid_sorts = {
        "-uploaded_at": "-uploaded_at",
        "uploaded_at": "uploaded_at",
        "filename": "original_filename",
        "-filename": "-original_filename",
        "-analyses": "-analyses_count",
    }
    order_field = valid_sorts.get(sort_by, "-uploaded_at")

    # Base queryset with counts and has_analysis annotation
    images = (
        GelImage.objects.select_related("uploaded_by")
        .annotate(
            analyses_count=Count("analyses"), has_analysis=Exists(GelAnalysis.objects.filter(gel_image=OuterRef("pk")))
        )
        .order_by(order_field)
    )

    # Apply filters
    if gel_type_filter:
        images = images.filter(gel_type=gel_type_filter)

    if analyzed_filter == "no":
        images = images.filter(has_analysis=False)
    elif analyzed_filter == "yes":
        images = images.filter(has_analysis=True)

    if search_query:
        images = images.filter(Q(original_filename__icontains=search_query) | Q(description__icontains=search_query))

    # KPIs - use annotation for non-analyzed count
    total_images = GelImage.objects.count()
    non_analyzed_count = (
        GelImage.objects.annotate(has_analysis=Exists(GelAnalysis.objects.filter(gel_image=OuterRef("pk"))))
        .filter(has_analysis=False)
        .count()
    )

    kpis = {
        "total": total_images,
        "non_analyzed": non_analyzed_count,
        "sds_page": GelImage.objects.filter(gel_type="SDS_PAGE").count(),
        "dot_blot": GelImage.objects.filter(gel_type="DOT_BLOT").count(),
        "western_blot": GelImage.objects.filter(gel_type="WESTERN_BLOT").count(),
    }

    # Pagination
    paginator = Paginator(images, 24)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_title": "Gel Images",
        "page_obj": page_obj,
        "images": page_obj.object_list,
        "kpis": kpis,
        "gel_type_choices": GelImage.GelType.choices,
        "gel_type_filter": gel_type_filter,
        "analyzed_filter": analyzed_filter,
        "search_query": search_query,
        "view_mode": view_mode,
        "sort_by": sort_by,
    }

    return render(request, "gel_analyzer/images/list.html", context)


@login_required
def image_upload_view(request):
    """
    Upload a new gel image.

    Handles:
    - Form submission with file validation
    - File processing (display image, thumbnail generation)
    - Format detection and metadata extraction
    """
    if request.method == "POST":
        form = GelImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                # Save the instance without committing
                gel_image = form.save(commit=False)
                gel_image.uploaded_by = request.user

                # Get the uploaded file
                uploaded_file = request.FILES["original_file"]
                gel_image.original_filename = uploaded_file.name

                # Validate file extension against allowlist
                suffix = Path(uploaded_file.name).suffix.lower()
                if suffix not in GelFileHandler.SUPPORTED_EXTENSIONS:
                    return JsonResponse({"error": f"Unsupported file format: {suffix}"}, status=400)

                # Save original file to a temp location for processing
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    for chunk in uploaded_file.chunks():
                        tmp.write(chunk)
                    tmp_path = Path(tmp.name)

                try:
                    # Process the file
                    result = GelFileHandler.process_uploaded_file(tmp_path)
                    metadata = result["metadata"]

                    # Set metadata fields
                    gel_image.file_format = metadata["format"]
                    gel_image.width = metadata["width"]
                    gel_image.height = metadata["height"]
                    gel_image.file_size_bytes = metadata["file_size_bytes"]

                    # Store scanner metadata from .scn files
                    if metadata.get("scn_metadata"):
                        gel_image.scanner_metadata = metadata["scn_metadata"]

                    # Save the instance to get a PK
                    gel_image.save()

                    # Generate file paths and save processed files
                    base_name = f"gel_{gel_image.pk}"

                    # Save display image
                    display_filename = f"{base_name}_display.png"
                    gel_image.display_file.save(display_filename, ContentFile(result["display_bytes"]), save=False)

                    # Save thumbnail
                    thumb_filename = f"{base_name}_thumb.png"
                    gel_image.thumbnail.save(thumb_filename, ContentFile(result["thumbnail_bytes"]), save=False)

                    # Save again with file references
                    gel_image.save()

                    logger.info(
                        f"Uploaded gel image: {gel_image.original_filename}",
                        user=request.user.username,
                        gel_image_id=str(gel_image.pk),
                    )

                    messages.success(request, f'Image "{gel_image.original_filename}" uploaded successfully!')
                    return redirect("gel_analyzer:image_detail", pk=gel_image.pk)

                finally:
                    # Clean up temp file
                    with contextlib.suppress(Exception):
                        tmp_path.unlink()

            except ValueError as e:
                logger.warning(f"Upload validation error: {e}", user=request.user.username)
                messages.error(request, f"Upload failed: {e}")
            except Exception as e:
                logger.exception(f"Upload error: {e}", user=request.user.username)
                messages.error(request, f"An error occurred during upload: {e}")
    else:
        form = GelImageUploadForm()

    context = {
        "page_title": "Upload Gel Image",
        "form": form,
    }

    return render(request, "gel_analyzer/images/upload.html", context)


@login_required
def image_detail_view(request, pk):
    """
    View gel image details including linked analyses.
    """
    gel_image = get_object_or_404(GelImage.objects.select_related("uploaded_by"), pk=pk)

    # Get analyses for this image
    analyses = gel_image.analyses.select_related("created_by").order_by("-created_at")

    context = {
        "page_title": gel_image.original_filename or "Gel Image",
        "gel_image": gel_image,
        "analyses": analyses,
    }

    return render(request, "gel_analyzer/images/detail.html", context)


@login_required
def image_delete_view(request, pk):
    """
    Delete a gel image.

    Requires confirmation via POST.
    Only the uploader or staff can delete.
    Blocks deletion if any associated analysis is COMPLETED or APPROVED.
    """
    gel_image = get_object_or_404(GelImage, pk=pk)

    # S4: Ownership check — only uploader or staff can delete
    if gel_image.uploaded_by != request.user and not request.user.is_staff:
        messages.error(request, "You do not have permission to delete this image.")
        return redirect("gel_analyzer:image_detail", pk=pk)

    # S3: Block deletion if any analysis is in a protected status
    protected_analyses = gel_image.analyses.filter(
        status__in=[GelAnalysis.Status.COMPLETED, GelAnalysis.Status.APPROVED]
    )
    if protected_analyses.exists():
        status_list = ", ".join(a.get_status_display() for a in protected_analyses[:5])
        messages.error(
            request,
            f"Cannot delete this image — it has analyses in protected status: {status_list}. "
            f"Please reject or revert these analyses first.",
        )
        return redirect("gel_analyzer:image_detail", pk=pk)

    if request.method == "POST":
        filename = gel_image.original_filename
        gel_image.delete()

        logger.info(f"Deleted gel image: {filename}", user=request.user.username, gel_image_id=str(pk))

        messages.success(request, f'Image "{filename}" deleted successfully.')
        return redirect("gel_analyzer:image_list")

    context = {
        "page_title": f"Delete {gel_image.original_filename}",
        "gel_image": gel_image,
    }

    return render(request, "gel_analyzer/images/delete.html", context)

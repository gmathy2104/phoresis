"""
Image views for Gel Analyzer.

Provides:
- image_list_view: List the images: pill filters (assay, gel type, uploader, analyzed), cards or table
- image_upload_view: Upload new images
- image_detail_view: An image and its analyses
- image_edit_view: Edit an image's gel type, assay and description (writers only)
- image_delete_view: Delete an image
"""

import contextlib
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import CharField, Count, Exists, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from gel_analyzer.access import user_can_write_gel_analyzer
from gel_analyzer.forms.image_forms import GelImageEditForm, GelImageUploadForm
from gel_analyzer.models import GelAnalysis, GelAssay, GelImage, Lane
from gel_analyzer.services.file_handler import GelFileHandler
from gel_analyzer.services.list_filters import (
    NONE_VALUE,
    choice_values,
    facet,
    facet_chips,
    ids_q,
    int_values,
    remove_value_url,
    selected_values,
)
from gel_analyzer.services.scanner_checks import scanner_type_mismatch
from phoresis_core.logging_config import get_logger

logger = get_logger(__name__)


# key -> (order_by field, label of the Sort select)
_IMAGE_SORTS = {
    "-uploaded_at": ("-uploaded_at", "Newest first"),
    "uploaded_at": ("uploaded_at", "Oldest first"),
    "filename": ("original_filename", "Name A-Z"),
    "-filename": ("-original_filename", "Name Z-A"),
    "-analyses": ("-analyses_count", "Most analyses"),
}
_ANALYZED_CHOICES = [("", "All"), ("yes", "Analyzed"), ("no", "Not yet")]
_ANALYZED_CHIPS = {"yes": "Analyzed", "no": "Not analyzed"}


# The pills' counts are over ALL images, never cross-filtered by the other pills:
# a count that moves when another filter changes confuses more than it helps.


def _assay_facet(assay_ids, assay_none, without_assay):
    """Assay pill: the assays that have images, in their display order, then "No assay"."""
    assays = GelAssay.objects.annotate(n=Count("images")).order_by("display_order", "name")
    options = [(assay.pk, assay.name, assay.n) for assay in assays if assay.n or assay.pk in assay_ids]
    if without_assay or assay_none:
        options.append((NONE_VALUE, "No assay", without_assay))
    return facet("assay", "Assay", options, selected_values(assay_ids, assay_none))


def _gel_type_facet(gel_types, type_counts):
    """Gel type pill: the gel types that have images, in their declared order."""
    options = [
        (value, label, type_counts[value])
        for value, label in GelImage.GelType.choices
        if type_counts[value] or value in gel_types
    ]
    return facet("gel_type", "Gel type", options, gel_types)


def _uploader_facet(uploader_ids):
    """Uploaded-by pill: the users who uploaded images, by full name (else username)."""
    rows = (
        GelImage.objects.filter(uploaded_by__isnull=False)
        .order_by()
        .values("uploaded_by", "uploaded_by__first_name", "uploaded_by__last_name", "uploaded_by__username")
        .annotate(n=Count("pk"))
    )
    options = []
    for row in rows:
        full_name = f"{row['uploaded_by__first_name']} {row['uploaded_by__last_name']}".strip()
        options.append((row["uploaded_by"], full_name or row["uploaded_by__username"], row["n"]))
    options.sort(key=lambda option: option[1].lower())
    return facet("uploaded_by", "Uploaded by", options, selected_values(uploader_ids))


@login_required
def image_list_view(request):
    """
    List the gel images: a pill filter bar, cards or a table, paginated.

    The bar is one GET form (``images/list.html`` + ``partials/_filter_picker.html``),
    so every filter lives in the URL:

    - ``q``: search in the file name and the description
    - ``assay``: repeated ids, plus ``none`` for "No assay"
      (a single ``?assay=3`` from an older link keeps working)
    - ``gel_type``: repeated ``GelImage.GelType`` values (the single ``?gel_type=SDS_PAGE``
      of the page's select keeps working)
    - ``uploaded_by``: repeated user ids
    - ``analyzed``: ``yes`` / ``no`` (anything else = all)
    - ``sort`` (``_IMAGE_SORTS``), ``view`` (``cards`` / ``table``), ``page``

    Each image carries its analysis count and the latest analysis status.
    """
    params = request.GET
    search_query = params.get("q", "").strip()
    assay_ids, assay_none = int_values(params, "assay")
    gel_types = choice_values(params, "gel_type", GelImage.GelType.values)
    uploader_ids, _ = int_values(params, "uploaded_by")
    analyzed_filter = params.get("analyzed", "")
    if analyzed_filter not in _ANALYZED_CHIPS:
        analyzed_filter = ""
    view_mode = "table" if params.get("view") == "table" else "cards"
    sort_by = params.get("sort", "-uploaded_at")
    if sort_by not in _IMAGE_SORTS:
        sort_by = "-uploaded_at"

    images = (
        GelImage.objects.select_related("uploaded_by", "assay")
        .annotate(
            analyses_count=Count("analyses", distinct=True),
            has_analysis=Exists(GelAnalysis.objects.filter(gel_image=OuterRef("pk"))),
            latest_analysis_status=Subquery(
                GelAnalysis.objects.filter(gel_image=OuterRef("pk")).order_by("-created_at").values("status")[:1],
                output_field=CharField(),
            ),
        )
        # -pk breaks the ties ("Most analyses" has many) so a page never repeats an image.
        .order_by(_IMAGE_SORTS[sort_by][0], "-pk")
        .filter(
            ids_q("assay", assay_ids, assay_none),
            ids_q("uploaded_by", uploader_ids),
        )
    )
    if gel_types:
        images = images.filter(gel_type__in=gel_types)
    if analyzed_filter:
        images = images.filter(has_analysis=analyzed_filter == "yes")
    if search_query:
        images = images.filter(Q(original_filename__icontains=search_query) | Q(description__icontains=search_query))

    paginator = Paginator(images, 24)
    page_obj = paginator.get_page(params.get("page", 1))
    status_labels = dict(GelAnalysis.Status.choices)
    for image in page_obj.object_list:
        image.latest_status_label = status_labels.get(image.latest_analysis_status, image.latest_analysis_status)

    # One query for the header total and the counts the pills need beyond their own.
    totals = GelImage.objects.aggregate(
        total=Count("pk"),
        without_assay=Count("pk", filter=Q(assay__isnull=True)),
        **{value: Count("pk", filter=Q(gel_type=value)) for value in GelImage.GelType.values},
    )
    facets = [
        _assay_facet(assay_ids, assay_none, totals["without_assay"]),
        _gel_type_facet(gel_types, totals),
        _uploader_facet(uploader_ids),
    ]

    chips = facet_chips(params, facets)
    if analyzed_filter:
        chips.append(
            {"label": _ANALYZED_CHIPS[analyzed_filter], "url": remove_value_url(params, "analyzed", analyzed_filter)}
        )
    if search_query:
        chips.append({"label": f'Search: "{search_query}"', "url": remove_value_url(params, "q", params.get("q"))})

    # The KPI row of the Phoresis list page (images/list.html).
    kpis = {
        "total": totals["total"],
        "non_analyzed": GelImage.objects.filter(analyses__isnull=True).count(),
        "sds_page": totals[GelImage.GelType.SDS_PAGE],
        "dot_blot": totals[GelImage.GelType.DOT_BLOT],
        "western_blot": totals[GelImage.GelType.WESTERN_BLOT],
    }

    context = {
        "page_title": "Gel images",
        "page_obj": page_obj,
        "images": page_obj.object_list,
        "kpis": kpis,
        # The single gel-type select of the Phoresis page: the first ticked value.
        "gel_type_choices": GelImage.GelType.choices,
        "gel_type_filter": gel_types[0] if gel_types else "",
        "total_count": totals["total"],
        "facets": facets,
        "chips": chips,
        "analyzed_choices": _ANALYZED_CHOICES,
        "analyzed_filter": analyzed_filter,
        "search_query": search_query,
        "view_mode": view_mode,
        "sort_by": sort_by,
        "sort_choices": [(key, label) for key, (_, label) in _IMAGE_SORTS.items()],
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
                user_suffix = Path(uploaded_file.name).suffix.lower()
                if user_suffix not in GelFileHandler.SUPPORTED_EXTENSIONS:
                    return JsonResponse({"error": f"Unsupported file format: {user_suffix}"}, status=400)

                # Re-bind the suffix from the trusted allowlist instead of
                # passing the user-derived string straight through. Same
                # value but the data-flow now originates from a project
                # constant — recognised by static analysis as a sanitiser
                # (py/path-injection).
                for allowed in GelFileHandler.SUPPORTED_EXTENSIONS:
                    if allowed == user_suffix:
                        suffix = allowed
                        break
                else:  # unreachable — the allowlist check above already returned 400
                    return JsonResponse({"error": "Unsupported file format"}, status=400)

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
        "page_title": "Upload a gel image",
        "form": form,
    }

    return render(request, "gel_analyzer/images/upload.html", context)


@login_required
def image_detail_view(request, pk):
    """
    View a gel image and its analyses.
    """
    gel_image = get_object_or_404(GelImage.objects.select_related("uploaded_by", "assay"), pk=pk)

    analyses = list(gel_image.analyses.select_related("created_by").order_by("-created_at"))

    context = {
        "page_title": gel_image.original_filename or "Gel Image",
        "gel_image": gel_image,
        "analyses": analyses,
        "lanes_count": Lane.objects.filter(analysis__gel_image=gel_image).count(),
        "file_size_mb": gel_image.file_size_bytes / (1024 * 1024) if gel_image.file_size_bytes else None,
        "can_write": user_can_write_gel_analyzer(request.user),
        # Never blocks: a warning when the .scn scan mode contradicts the gel type.
        "scanner_warning": scanner_type_mismatch(gel_image),
    }

    return render(request, "gel_analyzer/images/detail.html", context)


@login_required
def image_edit_view(request, pk):
    """
    Edit an image's gel type, assay and description (not the file).

    Writers only (``user_can_write_gel_analyzer``), GET and POST alike: anyone
    else is sent back to the detail page.
    """
    gel_image = get_object_or_404(GelImage.objects.select_related("assay"), pk=pk)

    if not user_can_write_gel_analyzer(request.user):
        messages.error(request, "You do not have permission to edit this image.")
        return redirect("gel_analyzer:image_detail", pk=pk)

    if request.method == "POST":
        form = GelImageEditForm(request.POST, instance=gel_image)
        if form.is_valid():
            gel_image = form.save()
            logger.info(
                f"Edited gel image: {gel_image.original_filename}",
                user=request.user.username,
                gel_image_id=str(gel_image.pk),
                gel_type=gel_image.gel_type,
                assay_id=gel_image.assay_id,
            )
            messages.success(request, "Image updated")
            return redirect("gel_analyzer:image_detail", pk=gel_image.pk)
    else:
        form = GelImageEditForm(instance=gel_image)

    context = {
        "page_title": f"Edit {gel_image.original_filename}",
        "gel_image": gel_image,
        "form": form,
    }

    return render(request, "gel_analyzer/images/edit.html", context)


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

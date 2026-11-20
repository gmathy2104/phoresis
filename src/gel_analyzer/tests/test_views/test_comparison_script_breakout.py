"""A public saved comparison's name ran as HTML for every user who opened it (2026-09-27).

`sample_comparison_view` built `saved_comparison_json` with a bare `json.dumps` and the
template emitted it with `|safe` inside `<script>`. A `SavedComparison` with
`is_public=True` is opened by other users, so a name holding `</script><img ...>`
closed the block in their session. The same shape was fixed on the analysis detail,
densitometry and ladder studio pages; this cross-user case stands for them.
"""

import pytest

from django.contrib.auth import get_user_model
from django.urls import reverse

from gel_analyzer.models import SavedComparison, SavedComparisonLane

PAYLOAD = "</script><img src=x onerror=alert(1)>"


@pytest.mark.django_db
def test_a_public_saved_comparison_name_cannot_close_the_script_block(client, test_user, sample_lane):
    author = get_user_model().objects.create_user(username="author", password="pw")
    comparison = SavedComparison.objects.create(name=PAYLOAD, description=PAYLOAD, is_public=True, created_by=author)
    SavedComparisonLane.objects.create(saved_comparison=comparison, lane=sample_lane, order=0)
    client.force_login(test_user)

    response = client.get(reverse("gel_analyzer:sample_comparison"), {"comparison": str(comparison.pk)})

    html = response.content.decode()
    assert response.status_code == 200
    assert PAYLOAD not in html
    assert "\\u003C/script\\u003E\\u003Cimg src=x onerror=alert(1)\\u003E" in html

"""Whether one extracted field needs a person to look at it (FR-11, IT-108).

The rule is D022's: a field is left alone only when it was read cleanly *and*
scored as high as a clean double agreement between the two extractors. Anything
else goes to review, so this is a question about one field and nothing more. It
does not look across records, and it does not add anything to a queue -- the
review queue and the reviewer screen both call it, so they cannot disagree.

D022 is a proposal while the client has not confirmed that FR-11 routes by
score. If the answer is "review everything", this is simply never called.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# D016's ``agree`` constant, the highest score a field can earn. Kept as a copy
# because src/ does not import from spike/; tests/test_review_routing.py fails
# if it drifts from spike/confidence.py, so a recalibration cannot silently
# send every field to review (or clear ones it should not).
AGREE_CONFIDENCE = 0.97


def needs_review(field: Mapping[str, Any]) -> bool:
    """True unless the field is ``ok`` with a score of at least ``agree``.

    ``field`` is a D007 field object, e.g. what ``build_field`` returns. Status
    is checked first, so a high score never overrides a non-``ok`` status:
    both-blank fields score 0.97 but are ``no_data``. A missing score is the
    worst case, not a neutral one, and a missing key is treated the same way.
    """
    if field.get("status") != "ok":
        return True
    confidence = field.get("confidence")
    if confidence is None:
        return True
    return confidence < AGREE_CONFIDENCE

"""Azure Document Intelligence: hosted, requires a trained custom model.

Prebuilt models (e.g. "prebuilt-layout") return generic key-value pairs and
tables, not fields keyed by our field names -- there's no prebuilt model
for this card layout. Getting schema-matching output means training a
custom model on a handful of labeled cards via the Azure portal/SDK first,
which needs a live Azure account and hasn't been done -- that's a separate,
out-of-band step, not something this adapter does. Until a custom model
exists, ``is_available()`` is False and the runner skips this cleanly.

Set AZURE_DOC_INTEL_ENDPOINT, AZURE_DOC_INTEL_KEY, and AZURE_DOC_INTEL_MODEL_ID
(the trained custom model's ID) once that step is done.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from extraction.base import ExtractionResult


class AzureDocIntelExtractor:
    name = "azure-doc-intel"

    def is_available(self) -> bool:
        try:
            import azure.ai.documentintelligence  # noqa: F401
        except ImportError:
            return False
        return bool(
            os.environ.get("AZURE_DOC_INTEL_ENDPOINT")
            and os.environ.get("AZURE_DOC_INTEL_KEY")
            and os.environ.get("AZURE_DOC_INTEL_MODEL_ID")
        )

    def _client(self):
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential

        return DocumentIntelligenceClient(
            endpoint=os.environ["AZURE_DOC_INTEL_ENDPOINT"],
            credential=AzureKeyCredential(os.environ["AZURE_DOC_INTEL_KEY"]),
        )

    def extract(self, image_path: Path) -> ExtractionResult:
        client = self._client()
        model_id = os.environ["AZURE_DOC_INTEL_MODEL_ID"]

        with image_path.open("rb") as f:
            poller = client.begin_analyze_document(model_id, body=f)
        return parse_analyze_result(poller.result())


def parse_analyze_result(result) -> ExtractionResult:
    """Flatten an AnalyzeResult into fields + per-field confidence.

    Split out from ``extract`` so the shape handling is testable without an
    Azure account -- the SDK's field objects are mappings, so a plain dict of
    dicts stands in for one.
    """
    fields: dict[str, str] = {}
    # Azure returns a per-field confidence next to the value, so FR-10 costs
    # nothing here. {} rather than None: this engine can always produce one, so
    # an empty dict means the document came back with no fields at all -- a
    # different thing from an engine that has no confidence to give.
    confidence: dict[str, float] = {}
    for document in result.documents or []:
        for name, field in (document.fields or {}).items():
            value = (
                field.get("valueString")
                or field.get("content")
                or field.get("valueNumber")
                or ""
            )
            fields[name] = str(value)
            score = field.get("confidence")
            if score is not None:
                confidence[name] = float(score)

    # raw_text is the extracted fields as JSON rather than the SDK object: this
    # engine has no text response to quote, but run_benchmark saves raw_text per
    # card and --rescore replays it through parse_json_fields. Leaving it None
    # wrote an empty file, and a rescore then reported near-zero accuracy for a
    # run that had actually worked, with no warning.
    return ExtractionResult(
        fields=fields,
        raw_text=json.dumps(fields),
        confidence=confidence,
        cost_usd=None,
    )

"""Page numbers into the source PDFs are 1-based, and a 0 must say so.

``pages[page_number - 1]`` turns a 0 into ``pages[-1]``, so a bad upstream row
would put the last page of the unit into the ground-truth set under another
card's id -- wrong image, no error, and every accuracy figure measured against
it quietly wrong too.

No data/ and no PDF: the guard runs before anything is opened.
"""

from pathlib import Path

import pytest

from select_c1_c2_sample import extract_image


@pytest.mark.parametrize("page_number", [0, -1])
def test_a_page_number_below_one_is_rejected(page_number, tmp_path):
    with pytest.raises(ValueError, match="1-based"):
        extract_image(Path("no-such.pdf"), page_number, tmp_path / "out.png")

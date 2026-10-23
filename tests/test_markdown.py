from pathlib import Path

from pykeynote import Presentation

FIXTURES = Path(__file__).parent / "fixtures"


def test_transitions_deck_to_markdown():
    md = Presentation.open(FIXTURES / "transitions-basic-white.key").to_markdown()
    assert md == (
        "<!-- layout: Title & Bullets -->\n"
        "<!-- transition: dissolve 1.5s -->\n"
        "# Dissolve\n"
        "\n---\n\n"
        "<!-- layout: Title & Bullets -->\n"
        "<!-- transition: push 1.5s -->\n"
        "# Push\n"
        "\n---\n\n"
        "<!-- layout: Title & Bullets -->\n"
        "<!-- transition: magic move 1.5s -->\n"
        "# Magic Move\n"
        "\n---\n\n"
        "<!-- layout: Title & Bullets -->\n"
        "# None\n"
    )


def test_bullets_and_notes():
    deck = Presentation.open(FIXTURES / "layouts-basic-white.key")
    blocks = deck.to_markdown().split("\n---\n\n")
    assert len(blocks) == 17
    assert blocks[3] == (
        "<!-- layout: Title & Bullets -->\n"
        "# Title & Bullets\n"
        "\n"
        "- First bullet\n"
        "- Second bullet\n"
        "- Third bullet\n"
        "\n"
        "???\n"
        "Notes for Title & Bullets\n"
    )
    # Statement's body has no bullets, so its paragraphs are plain text.
    assert "\nFirst bullet\n\nSecond bullet\n" in blocks[11]

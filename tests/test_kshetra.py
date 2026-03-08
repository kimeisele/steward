"""Tests for the Kshetra — 25-element Sankhya mapping."""

from steward.kshetra import (
    JIVA,
    STEWARD_KSHETRA,
    TattvaMapping,
    enumerate_kshetra,
    get_category_elements,
    get_element_mapping,
    get_layer_elements,
)
from vibe_core.protocols.mahajanas.kapila.samkhya import (
    PrakritiCategory,
    PrakritiElement,
)


class TestKshetraCompleteness:
    """Verify all 24 Prakriti elements are mapped."""

    def test_all_24_elements_mapped(self):
        """Every PrakritiElement must have a steward mapping."""
        for element in PrakritiElement:
            assert element in STEWARD_KSHETRA, (
                f"PrakritiElement.{element.name} ({element.value}) not mapped in STEWARD_KSHETRA"
            )

    def test_exactly_24_mappings(self):
        assert len(STEWARD_KSHETRA) == 24

    def test_25th_element_is_jiva(self):
        assert JIVA.layer == "soul"
        assert JIVA.component == "LLMProvider"

    def test_enumerate_returns_25(self):
        result = enumerate_kshetra()
        assert len(result) == 25
        # Last one is JIVA
        assert result[-1]["element"] == "JIVA"
        assert result[-1]["number"] == "25"


class TestKshetraCategories:
    """Verify each Sankhya category has the right number of elements."""

    def test_antahkarana_has_4(self):
        elements = get_category_elements(PrakritiCategory.ANTAHKARANA)
        assert len(elements) == 4

    def test_tanmatra_has_5(self):
        elements = get_category_elements(PrakritiCategory.TANMATRA)
        assert len(elements) == 5

    def test_jnanendriya_has_5(self):
        elements = get_category_elements(PrakritiCategory.JNANENDRIYA)
        assert len(elements) == 5

    def test_karmendriya_has_5(self):
        elements = get_category_elements(PrakritiCategory.KARMENDRIYA)
        assert len(elements) == 5

    def test_mahabhuta_has_5(self):
        elements = get_category_elements(PrakritiCategory.MAHABHUTA)
        assert len(elements) == 5


class TestKshetraMapping:
    """Verify mapping quality and structure."""

    def test_all_mappings_are_tattva(self):
        for mapping in STEWARD_KSHETRA.values():
            assert isinstance(mapping, TattvaMapping)

    def test_all_mappings_have_module(self):
        for element, mapping in STEWARD_KSHETRA.items():
            assert mapping.module, f"{element.name} has empty module"

    def test_all_mappings_have_role(self):
        for element, mapping in STEWARD_KSHETRA.items():
            assert mapping.role, f"{element.name} has empty role"

    def test_get_element_mapping(self):
        m = get_element_mapping(PrakritiElement.BUDDHI)
        assert m is not None
        assert m.component == "Buddhi"
        assert m.layer == "decision"

    def test_get_element_mapping_missing(self):
        # All elements should be present, but test the API
        m = get_element_mapping(PrakritiElement.MANAS)
        assert m is not None
        assert m.component == "Manas"

    def test_get_layer_elements(self):
        decision = get_layer_elements("decision")
        assert len(decision) == 1
        assert decision[0].component == "Buddhi"

    def test_antahkarana_is_cognitive_pipeline(self):
        """Antahkarana elements map to steward's cognitive pipeline."""
        elements = get_category_elements(PrakritiCategory.ANTAHKARANA)
        layers = {e.layer for e in elements}
        assert "cognition" in layers  # Manas
        assert "decision" in layers  # Buddhi
        assert "identity" in layers  # Ahankara
        assert "awareness" in layers  # Citta

    def test_enumerate_has_categories(self):
        result = enumerate_kshetra()
        categories = {r["category"] for r in result}
        assert "antahkarana" in categories
        assert "tanmatra" in categories
        assert "jnanendriya" in categories
        assert "karmendriya" in categories
        assert "mahabhuta" in categories
        assert "para_prakriti" in categories  # Jiva

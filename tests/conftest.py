import pytest

from audio_articles.core.models import ExtractionResult, ScriptResult


@pytest.fixture
def sample_extraction() -> ExtractionResult:
    return ExtractionResult(
        title="The Future of Renewable Energy",
        body=(
            "Solar and wind power are growing faster than any other energy source. "
            "Costs have fallen over 90% in the last decade. "
            "Experts predict renewables will supply half of global electricity by 2030. "
            "The main challenge remains energy storage for nights and calm days. "
            "New battery technologies and green hydrogen are emerging as solutions."
        ),
        source_url="https://example.com/renewables",
        word_count=72,
    )


@pytest.fixture
def sample_script() -> ScriptResult:
    return ScriptResult(
        script=(
            "Renewable energy is transforming the world's power grids at record speed. "
            "Solar and wind costs have plummeted over 90 percent in just one decade, "
            "making them cheaper than fossil fuels in most markets. "
            "By 2030, experts project renewables will provide half of all global electricity. "
            "The last hurdle is storage — keeping the lights on when the sun doesn't shine "
            "and the wind doesn't blow. Emerging battery technologies and green hydrogen "
            "promise to close that gap, bringing us closer to a fully clean grid."
        ),
        word_count=98,
        chunks_used=1,
    )

from conftest import FIXTURES

from costaudit.cli import main


def test_report_end_to_end(tmp_path):
    out = tmp_path / "report.md"
    main(
        [
            "snowflake",
            str(FIXTURES / "snowflake_queries.csv"),
            "--credit-price",
            "3",
            "--metering",
            str(FIXTURES / "snowflake_metering.csv"),
            "-o",
            str(out),
        ]
    )
    text = out.read_text()
    assert text.startswith("# Warehouse cost audit")
    assert "Compute actually billed" in text and "## Most expensive query patterns" in text
    assert text.index("kept running all day") < text.index("polling the warehouse")

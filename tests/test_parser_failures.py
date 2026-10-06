from emg_collector.acquisition.parser import LineParser


RAW_INPUT = """time_us,biceps_env,biceps_raw,brachio_env,brachio_raw

rst:0x1 (POWERON_RESET)
1000,100,200,300,400
bad,row
3000,abc,210,300,400
5000,4096,220,300,400
7000,120,-1,300,400
9000,130,230,300,400
"""


def test_parser_handles_mixed_valid_and_invalid_lines():
    parser = LineParser()
    lines = RAW_INPUT.splitlines()

    samples = parser.parse_lines(lines)

    assert [
        (_s.time_us, _s.biceps_env, _s.biceps_raw, _s.brachio_env, _s.brachio_raw)
        for _s in samples
    ] == [
        (1000, 100, 200, 300, 400),
        (9000, 130, 230, 300, 400),
    ]

    diag = parser.diagnostics
    assert diag.valid_rows == 2
    assert diag.header_lines == 1
    assert diag.blank_lines == 1
    assert diag.boot_message_lines == 1
    assert diag.malformed_rows == 2  # "bad,row" and "3000,abc,210,300,400"
    assert diag.out_of_range_rows == 2  # biceps_env=4096 and biceps_raw=-1


def test_parser_never_raises_on_arbitrary_garbage():
    parser = LineParser()
    garbage_lines = [
        "",
        "   ",
        ",,,,,",
        "1,2",
        "1,2,3,4",
        "1,2,3,4,5,6",
        "1e9,2,3,4,5",
        "1,2,3,4,5\x00",
        "☃,☃,☃,☃,☃",
    ]

    for line in garbage_lines:
        # Must never raise, regardless of content.
        parser.parse_line(line)

    assert parser.diagnostics.valid_rows == 0

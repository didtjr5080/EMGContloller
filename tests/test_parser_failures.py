from emg_collector.acquisition.parser import LineParser


RAW_INPUT = """time_us,env,raw

rst:0x1 (POWERON_RESET)
1000,100,200
bad,row
3000,abc,210
5000,4096,220
7000,120,-1
9000,130,230
"""


def test_parser_handles_mixed_valid_and_invalid_lines():
    parser = LineParser()
    lines = RAW_INPUT.splitlines()

    samples = parser.parse_lines(lines)

    assert [(_s.time_us, _s.env, _s.raw) for _s in samples] == [
        (1000, 100, 200),
        (9000, 130, 230),
    ]

    diag = parser.diagnostics
    assert diag.valid_rows == 2
    assert diag.header_lines == 1
    assert diag.blank_lines == 1
    assert diag.boot_message_lines == 1
    assert diag.malformed_rows == 2  # "bad,row" and "3000,abc,210"
    assert diag.out_of_range_rows == 2  # env=4096 and raw=-1


def test_parser_never_raises_on_arbitrary_garbage():
    parser = LineParser()
    garbage_lines = [
        "",
        "   ",
        ",,,",
        "1,2",
        "1,2,3,4",
        "1e9,2,3",
        "1,2,3\x00",
        "☃,☃,☃",
    ]

    for line in garbage_lines:
        # Must never raise, regardless of content.
        parser.parse_line(line)

    assert parser.diagnostics.valid_rows == 0

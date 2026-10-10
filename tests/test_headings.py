from minerupress.headings import analyze_headings, print_yaml


def test_headings_separates_toc_from_body_and_suggests_yaml(capsys) -> None:
    segments = [
        (
            "book_part1",
            [
                {"type": "text", "text_level": 1, "page_idx": 2, "text": "第1章 引论 …… 3"},
                {"type": "text", "text_level": 1, "page_idx": 20, "text": "第 1 章"},
                {"type": "text", "text_level": 1, "page_idx": 20, "text": "引 论"},
                {"type": "text", "text_level": 1, "page_idx": 30, "text": "附录 A"},
                {"type": "text", "text_level": 1, "page_idx": 30, "text": "术语表"},
            ],
        )
    ]

    candidates = analyze_headings(segments, toc_max_page=10, include_toc=True)

    assert candidates[0].is_toc_like is True
    assert candidates[0].confidence == "low"
    assert candidates[1].is_toc_like is False
    assert candidates[1].title == "引论"
    assert candidates[1].start_pattern == r"^第\s*1\s*章$"
    assert candidates[2].kind == "appendix"
    assert candidates[2].title == "术语表"

    print_yaml(candidates)
    yaml = capsys.readouterr().out

    assert "slug: ch01" in yaml
    assert "title: 第1章 引论" in yaml
    assert "slug: appendix-a" in yaml
    assert "title: 附录A 术语表" in yaml


def test_headings_includes_aside_text_chapter_candidates() -> None:
    segments = [
        (
            "book_part1",
            [
                {"type": "aside_text", "page_idx": 16, "text": "第1章\n绪论"},
                {"type": "text", "text_level": 1, "page_idx": 16, "text": "1.1 通信的基本概念"},
            ],
        )
    ]

    candidates = analyze_headings(segments, toc_max_page=10, include_toc=True)

    assert candidates[0].kind == "chapter"
    assert candidates[0].title == "绪论"
    assert candidates[0].start_pattern == r"^第\s*1\s*章$"

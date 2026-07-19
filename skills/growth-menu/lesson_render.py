from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

NAVY = RGBColor(28, 42, 62)
BLUE = RGBColor(58, 87, 122)
PALE = RGBColor(239, 243, 247)
WHITE = RGBColor(255, 255, 255)
DARK = RGBColor(35, 42, 50)
MUTED = RGBColor(88, 99, 110)
LINE = RGBColor(207, 216, 225)
ACCENT = RGBColor(104, 126, 153)


def set_text(shape, text: str, font_name: str, font_size: int, *, bold: bool = False,
             color: RGBColor = DARK, align: PP_ALIGN = PP_ALIGN.LEFT,
             margin: float = 0.12, valign: MSO_ANCHOR = MSO_ANCHOR.TOP) -> None:
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = Inches(margin)
    tf.margin_right = Inches(margin)
    tf.margin_top = Inches(margin)
    tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = font_name
    r_pr = run._r.get_or_add_rPr()
    east_asia = r_pr.find(qn("a:ea"))
    if east_asia is None:
        east_asia = OxmlElement("a:ea")
        r_pr.append(east_asia)
    east_asia.set("typeface", font_name)
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color


def add_card(slide, x: float, y: float, w: float, h: float, text: str, config: dict[str, Any],
             *, fill: RGBColor = WHITE, line: RGBColor = LINE, font_size: int | None = None,
             bold: bool = False, color: RGBColor = DARK, align: PP_ALIGN = PP_ALIGN.LEFT) -> Any:
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    shape.line.color.rgb = line
    set_text(shape, text, config["output"]["font_family"], font_size or config["output"]["body_pt"],
             bold=bold, color=color, align=align)
    return shape


def add_header(slide, title: str, subtitle: str, config: dict[str, Any]) -> None:
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.72))
    band.fill.solid()
    band.fill.fore_color.rgb = NAVY
    band.line.fill.background()
    set_text(band, title, config["output"]["font_family"], config["output"]["title_pt"],
             bold=True, color=WHITE, margin=0.2, valign=MSO_ANCHOR.MIDDLE)
    sub = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.35), Inches(0.12), Inches(4.65), Inches(0.45))
    sub.fill.background()
    sub.line.fill.background()
    set_text(sub, subtitle, config["output"]["font_family"], config["output"]["note_pt"],
             color=WHITE, align=PP_ALIGN.RIGHT, margin=0.02, valign=MSO_ANCHOR.MIDDLE)


def add_footer(slide, text: str, config: dict[str, Any]) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.35), Inches(7.08), Inches(12.63), Inches(0.25))
    shape.fill.background()
    shape.line.fill.background()
    set_text(shape, text, config["output"]["font_family"], config["output"]["note_pt"],
             color=MUTED, margin=0.01, valign=MSO_ANCHOR.MIDDLE)


def add_arrow(slide, x: float, y: float, w: float, h: float) -> None:
    arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = ACCENT
    arrow.line.fill.background()


def render_pptx(data: dict[str, Any], config: dict[str, Any], output_path: Path) -> None:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    slide = prs.slides.add_slide(blank)
    add_header(slide, data["title"], "HOS Morning Lesson", config)
    add_card(slide, 0.45, 1.02, 12.43, 0.9, f"今日のテーマ\n{data['focus_summary']}",
             config, fill=PALE, line=BLUE, bold=True, font_size=config["output"]["closing_pt"])
    lesson = data["business_lesson"]
    add_card(slide, 0.45, 2.18, 5.95, 1.6, f"なぜ学ぶか\n{lesson['why_it_matters']}", config)
    goals = "\n".join(f"{i+1}. {item}" for i, item in enumerate(lesson["learning_points"]))
    add_card(slide, 6.67, 2.18, 6.21, 1.6, f"今日わかるようになること\n{goals}", config, fill=WHITE, line=BLUE)
    add_card(slide, 0.45, 4.08, 12.43, 1.15, f"前回からつなぐ視点\n{data['previous_feedback_summary']}",
             config, fill=PALE, line=LINE)
    add_card(slide, 0.45, 5.52, 12.43, 0.88,
             f"学習の順番：理論 → ケース → 英文法　　所要時間：約{data['estimated_minutes']}分",
             config, bold=True, align=PP_ALIGN.CENTER)
    add_footer(slide, "読むだけで終わらず、各スライドで『なぜそうなるか』を一度言葉にする。", config)

    slide = prs.slides.add_slide(blank)
    add_header(slide, lesson["title"], "Theory", config)
    add_card(slide, 0.45, 0.98, 12.43, 1.0, f"基本概念\n{lesson['definition']}",
             config, fill=PALE, line=BLUE, bold=True)
    for i, point in enumerate(lesson["learning_points"]):
        add_card(slide, 0.45 + i * 4.18, 2.25, 3.92, 1.38, f"ポイント{i+1}\n{point}",
                 config, fill=WHITE, line=LINE)
    chain = lesson["cause_effect_chain"]
    x_positions = [0.55, 4.78, 9.0]
    for i, item in enumerate(chain):
        add_card(slide, x_positions[i], 4.02, 3.42, 1.02, item, config, fill=PALE, line=BLUE,
                 bold=True, align=PP_ALIGN.CENTER)
        if i < 2:
            add_arrow(slide, x_positions[i] + 3.52, 4.32, 0.58, 0.38)
    add_card(slide, 0.45, 5.42, 12.43, 0.95, f"よくある混同\n{lesson['common_confusion']}",
             config, fill=WHITE, line=BLUE)
    add_footer(slide, "フレームワーク名を覚えるより、因果関係を説明できることを優先する。", config)

    case = data["case_lesson"]
    slide = prs.slides.add_slide(blank)
    add_header(slide, case["title"], "Case Application", config)
    add_card(slide, 0.45, 0.98, 12.43, 0.92, f"ケースの状況\n{case['context']}", config, fill=PALE, line=BLUE)
    obs_text = "\n".join(f"・{item}" for item in case["observations"])
    int_text = "\n".join(f"・{item}" for item in case["interpretation"])
    add_card(slide, 0.45, 2.18, 5.95, 2.35, f"観察できること\n{obs_text}", config)
    add_card(slide, 6.67, 2.18, 6.21, 2.35, f"理論で読み解くと\n{int_text}", config, fill=WHITE, line=BLUE)
    add_card(slide, 0.45, 4.85, 12.43, 1.25, f"このケースからの要点\n{case['takeaway']}",
             config, fill=PALE, line=BLUE, bold=True, font_size=config["output"]["closing_pt"])
    add_footer(slide, f"教材区分：{case['reference_label']}。時点で変わる企業数値は使用しない。", config)

    english = data["english_lesson"]
    slide = prs.slides.add_slide(blank)
    add_header(slide, english["title"], "Business English", config)
    add_card(slide, 0.45, 0.98, 12.43, 0.75, f"今日の型：{english['grammar_pattern']}",
             config, fill=PALE, line=BLUE, bold=True, font_size=config["output"]["closing_pt"])
    rules = "\n".join(f"{i+1}. {item}" for i, item in enumerate(english["rule_points"]))
    add_card(slide, 0.45, 1.98, 4.05, 1.6, f"ルール\n{rules}", config)
    add_card(slide, 4.73, 1.98, 3.92, 1.6, f"誤り例\n{english['bad_example']}", config)
    add_card(slide, 8.88, 1.98, 4.0, 1.6, f"正解例\n{english['correct_example']}", config, fill=WHITE, line=BLUE)
    breakdown = " / ".join(english["example_breakdown"])
    add_card(slide, 0.45, 3.85, 12.43, 0.7, f"文の分解：{breakdown}", config,
             font_size=config["output"]["note_pt"])
    vocab_text = " / ".join(f"{item['word']}（{item['meaning']}）" for item in english["vocabulary"])
    add_card(slide, 0.45, 4.78, 12.43, 0.78, f"今日の5語：{vocab_text}", config,
             fill=PALE, line=LINE, font_size=config["output"]["note_pt"])
    add_card(slide, 0.45, 5.78, 7.75, 0.78,
             f"例文\n{english['worked_example_ja']}\n{english['worked_example_en']}",
             config, font_size=config["output"]["note_pt"])
    add_card(slide, 8.45, 5.78, 4.43, 0.78, f"ミニ練習\n{english['practice_prompt']}",
             config, fill=WHITE, line=BLUE, font_size=config["output"]["note_pt"], bold=True)
    add_footer(slide, "英語は長さより、主語・動詞・接続を崩さず2文で書く。", config)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(output_path)


def write_outputs(data: dict[str, Any], config: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "history").mkdir(parents=True, exist_ok=True)
    date_slug = data["date"]
    latest_json = output_dir / "latest.json"
    history_json = output_dir / "history" / f"{date_slug}.json"
    latest_pptx = output_dir / "latest.pptx"
    history_pptx = output_dir / "history" / f"{date_slug}_growth_lesson.pptx"
    notification = output_dir / "latest_notification.md"

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    latest_json.write_text(text, encoding="utf-8")
    history_json.write_text(text, encoding="utf-8")
    render_pptx(data, config, latest_pptx)
    history_pptx.write_bytes(latest_pptx.read_bytes())
    raw_url = "https://raw.githubusercontent.com/purachinaevo7-cmyk/HOS/main/outputs/growth-menu/latest.pptx"
    notification.write_text(
        f"## {data['notification']['headline']}\n\n"
        f"{data['notification']['summary']}\n\n"
        f"所要時間：{data['notification']['duration']}\n\n"
        f"[今日のPowerPoint授業を開く]({raw_url})\n\n"
        "学習後は、このチャットに次の3点を返してください。\n"
        "1. 今日理解したこと\n"
        "2. ケースに対する自分の見解\n"
        "3. スライド4の英作文\n",
        encoding="utf-8"
    )
    return {
        "latest_json": latest_json,
        "history_json": history_json,
        "latest_pptx": latest_pptx,
        "history_pptx": history_pptx,
        "notification": notification
    }

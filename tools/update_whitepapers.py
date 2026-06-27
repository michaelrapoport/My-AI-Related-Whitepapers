import argparse
import html
import json
import re
import shutil
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


SOURCE_ROOT = Path(r"C:\Users\mikea\Documents\- Patent Stuff")
REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_BASE = "https://michaelrapoport.github.io/My-AI-Related-Whitepapers"

AI_TERMS = re.compile(
    r"\b(ai|artificial intelligence|machine learning|deep learning|neural|neuromorphic|"
    r"pinn|physics[- ]informed|piml|llm|rag|transformer|reinforcement|bayesian|"
    r"graph neural|gnn|digital twin|generative|adversarial|surrogate model|agentic)\b",
    re.I,
)

PAPER_TERMS = re.compile(
    r"\b(whitepaper|scientific paper|research paper|abstract|introduction|methodology|"
    r"results|discussion|conclusion)\b",
    re.I,
)

EXCLUDE = re.compile(
    r"(ai_studio_code|node_modules|site-packages|__pycache__|\.git|package-lock|"
    r"patent_application|non[_ -]?provisional|provisional|claims?|office_action|"
    r"debug|commonjs|mockagent|mockpool|baselinebrowsermapping|changelog)",
    re.I,
)


@dataclass
class Paper:
    title: str
    slug: str
    category: str
    subcategory: str
    source: Path
    abstract: str
    summary: str
    body_html: str


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "svg"}:
            self.skip += 1
        elif tag.lower() in {"p", "br", "h1", "h2", "h3", "li"} and not self.skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "svg"} and self.skip:
            self.skip -= 1
        elif tag.lower() in {"p", "h1", "h2", "h3", "li"} and not self.skip:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    @property
    def text(self):
        return re.sub(r"\n{3,}", "\n\n", html.unescape(" ".join(self.parts))).strip()


def read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc, errors="strict")
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def strip_html_text(raw: str) -> str:
    parser = TextExtractor()
    try:
        parser.feed(raw)
        return parser.text
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)


def slugify(title: str) -> str:
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:72] or "untitled-paper"


def clean_title(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\.[a-z0-9]+$", "", value, flags=re.I)
    value = re.sub(r"^\[?whitepaper\]?\s*[-_ ]*", "", value, flags=re.I)
    value = re.sub(r"^_?paper_+\s*", "", value, flags=re.I)
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_[]")
    if value.isupper() or value.islower():
        value = value.title()
    return value


def extract_title(path: Path, raw: str, text: str) -> str:
    for pattern in (
        r"<h1[^>]*>(.*?)</h1>",
        r"<h2[^>]*>(.*?)</h2>",
        r"<title[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, raw, re.I | re.S)
        if match:
            candidate = clean_title(re.sub(r"<[^>]+>", " ", match.group(1)))
            if 8 <= len(candidate) <= 180 and not re.search(r"patent application|claim", candidate, re.I):
                return candidate
    lines = [clean_title(line) for line in text.splitlines() if len(line.strip()) > 8]
    for line in lines[:12]:
        if len(line) <= 180 and not re.search(r"abstract|copyright|doctype|html", line, re.I):
            return line
    return clean_title(path.stem)


def extract_body(raw: str) -> str:
    body = raw
    match = re.search(r"<body[^>]*>(.*?)</body>", raw, re.I | re.S)
    if match:
        body = match.group(1)
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.I | re.S)
    body = re.sub(r"<style\b.*?</style>", "", body, flags=re.I | re.S)
    body = re.sub(r"<!DOCTYPE[^>]*>", "", body, flags=re.I)
    body = re.sub(r"</?(html|head|body|meta|title)[^>]*>", "", body, flags=re.I)
    body = body.strip()
    if "<p" not in body.lower() and "<h" not in body.lower():
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", strip_html_text(raw)) if p.strip()]
        body = "\n".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
    return body


def extract_abstract(text: str) -> str:
    match = re.search(r"abstract\s*[:\n]\s*(.{220,1800}?)(?:\n\s*(?:1\.|introduction|background|keywords)\b)", text, re.I | re.S)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 160]
    return (paras[0] if paras else text[:800]).strip()


def classify_paper(title: str, text: str) -> tuple[str, str]:
    title_hay = title.lower()
    hay = f"{title} {text[:4000]}".lower()
    priority_checks = [
        ("Physics-Informed & Scientific ML", "Physics-Informed Neural Networks", r"physics-informed|physics informed|pinn|piml"),
        ("Physics-Informed & Scientific ML", "Digital Twins & Surrogate Models", r"digital twin|surrogate model|predictive model"),
        ("Physics-Informed & Scientific ML", "Differentiable Simulation & Sensitivity Gradients", r"differentiable|sensitivity gradient|gradient architecture|gradient trainer"),
        ("Physics-Informed & Scientific ML", "Materials Discovery & Co-Optimization", r"material|synthesis|catalytic|battery|semiconductor|alloy|polymer"),
        ("Neural, Neuromorphic & Cognitive Systems", "Neuromorphic Hardware & Memristive Learning", r"neuromorphic|memrist|synaptic|neural mesh|neural engine|neural parity"),
        ("Neural, Neuromorphic & Cognitive Systems", "Brain-Computer Interfaces & Neural Decoding", r"brain|cortical|emg|neuro-haptic|neuromuscular|sub-vocal|neural knowledge|electrode"),
        ("Neural, Neuromorphic & Cognitive Systems", "Human-AI Alignment & Cognitive Interfaces", r"somatic|intent|agi interface|human-ai|cognitive|latent synchronization"),
        ("Neural, Neuromorphic & Cognitive Systems", "Model Optimization & Learning Architectures", r"model pruning|neural network|deep learning|classifier|training"),
        ("Generative AI & Knowledge Systems", "LLMs, RAG & Knowledge Retrieval", r"rag|retrieval|knowledge|large language|llm"),
        ("Generative AI & Knowledge Systems", "Semantic Protocols & Intent Translation", r"semantic|natural language|bytecode|transcoder|speech-to-intent"),
        ("Generative AI & Knowledge Systems", "Compliance, Safety & Decision Libraries", r"compliance|prohibited state|policy|audit|safety"),
        ("Generative AI & Knowledge Systems", "Latent Alignment & Agentic Systems", r"generative|latent alignment|agentic"),
        ("Bio, Medical & Environmental AI", "Drug Discovery & Nanocarriers", r"drug|pharma|nanocarrier|inhibitor|regenerative medicine|therapeutic"),
        ("Bio, Medical & Environmental AI", "Bio-Hybrid Systems & Bioremediation", r"bio-hybrid|bioremediation|bio scrubber|bioreactor|metabolic"),
        ("Bio, Medical & Environmental AI", "Medical Interfaces & Therapeutics", r"medical|clinical|prosthetic|dental|topical kit"),
        ("AI Hardware, Edge & Infrastructure", "Edge, FPGA & ASIC Acceleration", r"edge|fpga|asic|chip|on-chip|accelerator|precision hardware"),
        ("AI Hardware, Edge & Infrastructure", "Memristive, Crossbar & In-Memory Compute", r"memrist|crossbar|in-memory|volatile non volatile"),
        ("AI Hardware, Edge & Infrastructure", "Energy-Aware AI Infrastructure", r"energy|thermal|self powered|low-power|power"),
        ("Autonomous & Robotic Systems", "Swarm, Fleet & Mission Autonomy", r"swarm|fleet|mission|multi-agent"),
        ("Autonomous & Robotic Systems", "Autonomous Safety & Navigation", r"autonomous|robot|drone|uav|vehicle|navigation"),
        ("Security, Finance & Decision Intelligence", "Security, Risk & Fraud Intelligence", r"secure|security|threat|fraud|risk|ledger|blockchain|federated"),
        ("AI Control & Signal Systems", "Beamforming & Phased-Array Control", r"beamforming|phased array|phased arrays|array control|antenna"),
        ("AI Control & Signal Systems", "Hydraulic, Fluidic & Turbulence Control", r"hydraulic|fluidic|nanofluidic|turbulence|flow control|valve|manifold"),
        ("AI Control & Signal Systems", "Predictive Maintenance & Sensor Fusion", r"predictive maintenance|sensor fusion|condition monitoring"),
        ("AI Control & Signal Systems", "Metamaterials & Active Matter Control", r"metamaterial|active matter"),
        ("AI Control & Signal Systems", "Acoustic, Waveform & Resonance Control", r"acoustic|waveform|resonance|vibration|phase locked|phase-adaptive|interference"),
        ("AI Control & Signal Systems", "Adaptive Control & Optimization", r"adaptive|feedback|controller|control|governor|calibration|modulation|tuner"),
    ]
    for category, subcategory, pattern in priority_checks:
        if re.search(pattern, title_hay):
            return category, subcategory

    checks = [
        ("AI Control & Signal Systems", "Acoustic, Waveform & Resonance Control", r"acoustic|waveform|resonance|vibration|phase|modulation|cavitation|harmonic"),
        ("AI Control & Signal Systems", "Beamforming & Phased-Array Control", r"beamforming|phased array|array control|antenna|directional|spatial filtering"),
        ("AI Control & Signal Systems", "Bio-Signal & Neuro-Control Interfaces", r"brain|neuro|bci|prosthetic|biosignal|bio-signal|neural decoding|electrode"),
        ("AI Control & Signal Systems", "Hydraulic, Fluidic & Turbulence Control", r"hydraulic|fluidic|fluid dynamics|turbulence|flow control|pump|valve"),
        ("AI Control & Signal Systems", "Predictive Maintenance & Sensor Fusion", r"predictive maintenance|sensor fusion|fault|threshold|condition monitoring|diagnostic"),
        ("AI Control & Signal Systems", "Metamaterials & Active Matter Control", r"metamaterial|active matter|reconfigurable material|smart material"),
        ("AI Control & Signal Systems", "Adaptive Control & Optimization", r"control|adaptive|feedback|controller|optimization|optimal control"),
        ("Physics-Informed & Scientific ML", "Physics-Informed Neural Networks", r"physics-informed|pinn|piml|physics informed"),
        ("Physics-Informed & Scientific ML", "Digital Twins & Surrogate Models", r"digital twin|surrogate model|reduced-order|reduced order|emulator"),
        ("Physics-Informed & Scientific ML", "Differentiable Simulation & Sensitivity Gradients", r"differentiable|gradient|sensitivity|adjoint|simulation"),
        ("Physics-Informed & Scientific ML", "Materials Discovery & Co-Optimization", r"material|synthesis|catalytic|battery|semiconductor|alloy|polymer"),
        ("Physics-Informed & Scientific ML", "Scientific Computing & Analog Simulation", r"scientific machine|scientific computing|analog|numerical|finite element|computational"),
        ("Neural, Neuromorphic & Cognitive Systems", "Neuromorphic Hardware & Memristive Learning", r"neuromorphic|memrist|crossbar|synaptic|spiking"),
        ("Neural, Neuromorphic & Cognitive Systems", "Brain-Computer Interfaces & Neural Decoding", r"brain-computer|bci|neural decoding|neuro|prosthetic"),
        ("Neural, Neuromorphic & Cognitive Systems", "Human-AI Alignment & Cognitive Interfaces", r"human-ai|alignment|cognitive|intent|preference|interactive"),
        ("Neural, Neuromorphic & Cognitive Systems", "Model Optimization & Learning Architectures", r"neural|transformer|deep learning|reinforcement|gan|adversarial|bayesian|classifier|training|pruning|learning architecture"),
        ("Generative AI & Knowledge Systems", "LLMs, RAG & Knowledge Retrieval", r"llm|large language|rag|retrieval|language model|knowledge graph"),
        ("Generative AI & Knowledge Systems", "Semantic Protocols & Intent Translation", r"semantic|natural language|intent|compiler|bytecode|translation"),
        ("Generative AI & Knowledge Systems", "Compliance, Safety & Decision Libraries", r"compliance|policy|audit|risk|safety|decision library|governance"),
        ("Generative AI & Knowledge Systems", "Latent Alignment & Agentic Systems", r"agentic|agent|prompt|generative|latent"),
        ("Bio, Medical & Environmental AI", "Drug Discovery & Nanocarriers", r"drug|pharma|nanocarrier|protein|genomic|therapeutic"),
        ("Bio, Medical & Environmental AI", "Bio-Hybrid Systems & Bioremediation", r"bio-hybrid|bioremediation|cell|bioreactor|microbial|environmental"),
        ("Bio, Medical & Environmental AI", "Medical Interfaces & Therapeutics", r"medical|clinical|diagnosis|prosthetic|patient|therapy"),
        ("AI Hardware, Edge & Infrastructure", "Edge, FPGA & ASIC Acceleration", r"edge|fpga|asic|chip|on-chip|accelerator"),
        ("AI Hardware, Edge & Infrastructure", "Memristive, Crossbar & In-Memory Compute", r"memrist|crossbar|in-memory|neuromorphic"),
        ("AI Hardware, Edge & Infrastructure", "Energy-Aware AI Infrastructure", r"energy|thermal|power|efficiency|low-power"),
        ("Autonomous & Robotic Systems", "Swarm, Fleet & Mission Autonomy", r"swarm|fleet|mission|multi-agent|coordination"),
        ("Autonomous & Robotic Systems", "Autonomous Safety & Navigation", r"autonomous|robot|drone|uav|vehicle|navigation|path planning"),
        ("Security, Finance & Decision Intelligence", "Security, Risk & Fraud Intelligence", r"security|threat|fraud|risk|ledger|blockchain|finance"),
    ]
    for haystack in (title_hay, hay):
        for category, subcategory, pattern in checks:
            if re.search(pattern, haystack):
                return category, subcategory
    return "Advanced AI Systems", "Cross-Domain AI Research"


def make_summary(title: str, abstract: str, category: str, subcategory: str) -> str:
    cleaned = re.sub(r"\s+", " ", abstract).strip()
    cleaned = re.sub(r"^(abstract|summary)\s*[:.-]\s*", "", cleaned, flags=re.I)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    for sentence in sentences:
        sentence = sentence.strip()
        if 45 <= len(sentence) <= 280 and len(sentence.split()) <= 42:
            return sentence
    title_phrase = title.rstrip(".")
    focus = subcategory.lower()
    return f"Examines {title_phrase} as {focus} research, emphasizing AI-enabled modeling, prediction, control, or system design."


def candidate_paths():
    for path in SOURCE_ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm", ".txt", ".md"}:
            continue
        full = str(path)
        if EXCLUDE.search(full):
            continue
        if "_ORGANIZED_BY_DOMAIN_AND_VALUE" in full and "AI_MachineLearning" not in full:
            continue
        name_hit = AI_TERMS.search(path.stem) or PAPER_TERMS.search(path.stem)
        if not name_hit:
            continue
        yield path


def collect_papers(limit: int | None = None) -> list[Paper]:
    selected = {}
    for path in candidate_paths():
        raw = read_text(path)
        text = strip_html_text(raw)
        if len(text) < 1200:
            continue
        if not AI_TERMS.search(f"{path.stem} {text[:5000]}"):
            continue
        if not (PAPER_TERMS.search(f"{path.stem} {text[:5000]}") or "AI_MachineLearning" in str(path)):
            continue
        title = extract_title(path, raw, text)
        if len(title) < 8 or re.search(
            r"\b(class|function|debug|dispatcher|commonjs|mock)\b|^(abstract|title of the invention|root invention|united states patent application|strategic spin off portfolio|evolutionary innovation matrix)$",
            title,
            re.I,
        ):
            continue
        key = re.sub(r"[^a-z0-9]+", "", title.lower())
        abstract = extract_abstract(text)
        category, subcategory = classify_paper(title, text)
        paper = Paper(
            title=title,
            slug=slugify(title),
            category=category,
            subcategory=subcategory,
            source=path,
            abstract=abstract,
            summary=make_summary(title, abstract, category, subcategory),
            body_html=extract_body(raw),
        )
        prev = selected.get(key)
        if not prev or path.stat().st_size > prev.source.stat().st_size:
            selected[key] = paper
        if limit and len(selected) >= limit:
            break
    papers = sorted(selected.values(), key=lambda p: (p.category, p.subcategory, p.title.lower()))
    slugs = {}
    for paper in papers:
        base = paper.slug
        n = slugs.get(base, 0)
        slugs[base] = n + 1
        if n:
            paper.slug = f"{base}-{n + 1}"
    return papers


def collect_existing_pages() -> list[Paper]:
    papers = []
    for path in REPO_ROOT.glob("*.html"):
        if path.name == "index.html":
            continue
        raw = read_text(path)
        text = strip_html_text(raw)
        title = extract_title(path, raw, text)
        if len(title) < 8:
            continue
        abstract = extract_abstract(text)
        category, subcategory = classify_paper(title, text)
        papers.append(Paper(
            title=title,
            slug=path.stem,
            category=category,
            subcategory=subcategory,
            source=path,
            abstract=abstract,
            summary=make_summary(title, abstract, category, subcategory),
            body_html="",
        ))
    return papers


def merge_with_existing(source_papers: list[Paper]) -> list[Paper]:
    merged = {paper.slug: paper for paper in source_papers}
    normalized_titles = {re.sub(r"[^a-z0-9]+", "", paper.title.lower()) for paper in source_papers}
    for paper in collect_existing_pages():
        title_key = re.sub(r"[^a-z0-9]+", "", paper.title.lower())
        if paper.slug not in merged and title_key not in normalized_titles:
            merged[paper.slug] = paper
    return sorted(merged.values(), key=lambda p: (p.category, p.subcategory, p.title.lower()))


STYLE = """
body { font-family: 'Georgia', serif; line-height: 1.6; color: #333; max-width: 850px; margin: 0 auto; padding: 40px; background-color: #fcfcfc; }
header { border-bottom: 3px solid #1a2a6c; margin-bottom: 30px; padding-bottom: 20px; text-align: center; }
h1 { color: #1a2a6c; font-size: 2.2em; margin-bottom: 10px; line-height: 1.2; }
.author-box { margin-top: 10px; }
.author-name { font-weight: bold; font-size: 1.3em; color: #444; }
.affiliation { color: #777; font-style: italic; font-size: 1.1em; }
.abstract-container { background: #fff; padding: 25px; border: 1px solid #ddd; border-left: 6px solid #1a2a6c; margin: 30px 0; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
.abstract-title { font-weight: bold; text-transform: uppercase; font-size: 0.9em; letter-spacing: 1px; color: #1a2a6c; display: block; margin-bottom: 10px; }
.abstract-text { font-style: italic; text-align: justify; }
.content { text-align: justify; }
h2 { color: #1a2a6c; border-bottom: 1px solid #eee; padding-bottom: 5px; margin-top: 40px; }
h3 { color: #2a3a7c; margin-top: 30px; }
p { margin-bottom: 1.5em; }
footer { margin-top: 60px; border-top: 1px solid #eee; padding-top: 20px; font-size: 0.85em; color: #999; text-align: center; }
.back-link { display: inline-block; margin-bottom: 20px; color: #1a2a6c; text-decoration: none; font-weight: bold; }
.back-link:hover { text-decoration: underline; }
.support { margin-top: 40px; padding: 20px; background: #f4f7ff; border: 1px solid #d9e2ff; border-radius: 8px; text-align: left; }
.support a { color: #1a2a6c; font-weight: bold; }
"""


def render_paper(paper: Paper) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(paper.title)} - Whitepaper</title>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <style>{STYLE}</style>
</head>
<body>
    <a href="index.html" class="back-link">&larr; Back to Index</a>
    <header>
        <h1>{html.escape(paper.title)}</h1>
        <div class="author-box">
            <div class="author-name">Michael Rapoport</div>
            <div class="affiliation">Polaritronics, Inc.</div>
        </div>
    </header>
    <div class="abstract-container">
        <span class="abstract-title">Abstract</span>
        <div class="abstract-text">{html.escape(paper.abstract)}</div>
    </div>
    <div class="content">
{paper.body_html}
    </div>
    <div class="support">
        <strong>Support this research:</strong>
        If this work is useful, consider supporting continued AI research and publication through
        <a href="https://github.com/sponsors/michaelrapoport">GitHub Sponsors</a> or
        <a href="https://www.buymeacoffee.com/michaelrapoport">Buy Me a Coffee</a>.
    </div>
    <footer>
        &copy; 2026 Michael Rapoport, Polaritronics, Inc. All rights reserved. Professional Technical Document Series.
    </footer>
</body>
</html>
"""


def grouped(papers: list[Paper]):
    groups = {}
    for paper in papers:
        groups.setdefault(paper.category, {}).setdefault(paper.subcategory, []).append(paper)
    return dict(sorted(groups.items()))


def render_readme(papers: list[Paper]) -> str:
    lines = [
        "# 📄 My AI-Related Whitepapers",
        "### Research, Methods, and Systems in Artificial Intelligence",
        "",
        "[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)",
        "[![Research](https://img.shields.io/badge/Domain-AI%20%2F%20ML-blue.svg)](https://github.com/michaelrapoport/My-AI-Related-Whitepapers)",
        "[![Live Site](https://img.shields.io/badge/View-Whitepapers-green.svg)](https://michaelrapoport.github.io/My-AI-Related-Whitepapers/)",
        "",
        "**A curated collection of AI-related whitepapers covering neural systems, physics-informed ML, autonomous control, generative systems, industrial intelligence, and applied scientific machine learning.**",
        "",
        "## 🚀 Live Access",
        f"View the full research portal at: **[{SITE_BASE}/]({SITE_BASE}/)**",
        "",
        "## Support This Research",
        "If these papers are useful to your work, please consider supporting continued research, publication, and open technical exploration:",
        "",
        "- [Sponsor on GitHub](https://github.com/sponsors/michaelrapoport)",
        "- [Buy Me a Coffee](https://www.buymeacoffee.com/michaelrapoport)",
        "",
        "Your support helps fund experiments, writing, tooling, and the time needed to keep this research library organized and available.",
        "",
        "## 📚 Research & Publications",
        "",
    ]
    for category, subgroups in grouped(papers).items():
        lines.append(f"### {category}")
        for subcategory, items in sorted(subgroups.items()):
            lines.append(f"#### {subcategory}")
            for paper in items:
                lines.append(f"- [**{paper.title}**]({SITE_BASE}/{paper.slug}.html) - {paper.summary}")
            lines.append("")
        lines.append("")
    lines += [
        "---",
        "**Author**: M. Keith Rapoport  ",
        "**License**: MIT",
    ]
    return "\n".join(lines) + "\n"


def render_index(papers: list[Paper]) -> str:
    sections = []
    for category, subgroups in grouped(papers).items():
        subsections = []
        for subcategory, items in sorted(subgroups.items()):
            cards = []
            for paper in items:
                cards.append(f"""
        <article class="card">
            <h3>{html.escape(paper.title)}</h3>
            <div class="tag">{html.escape(subcategory)}</div>
            <p>{html.escape(paper.summary)}</p>
            <a href="{paper.slug}.html" class="btn">Read Whitepaper</a>
        </article>""")
            subsections.append(f"""
        <h3 class="subcategory">{html.escape(subcategory)}</h3>
        <div class="grid">{''.join(cards)}
        </div>""")
        sections.append(f"""
    <section>
        <h2>{html.escape(category)}</h2>
{''.join(subsections)}
    </section>""")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI-Related Whitepapers - Michael Rapoport</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; max-width: 1180px; margin: 0 auto; padding: 40px; background-color: #f4f7f6; }}
        header {{ background-color: #1a2a6c; color: white; padding: 40px; border-radius: 8px; margin-bottom: 30px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        h1 {{ margin: 0; font-size: 2.5em; }}
        h2 {{ color: #1a2a6c; border-bottom: 2px solid #d9e2ff; padding-bottom: 8px; margin-top: 42px; }}
        .subtitle {{ font-size: 1.2em; opacity: 0.9; margin-top: 10px; }}
        .support {{ background: white; padding: 24px; border-left: 6px solid #1a2a6c; border-radius: 8px; margin-bottom: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .support a {{ color: #1a2a6c; font-weight: 700; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 25px; }}
        .subcategory {{ color: #43538f; margin: 26px 0 14px; font-size: 1.05em; }}
        .card {{ background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); transition: transform 0.2s, box-shadow 0.2s; border-top: 4px solid #1a2a6c; display: flex; flex-direction: column; }}
        .card:hover {{ transform: translateY(-5px); box-shadow: 0 8px 15px rgba(0,0,0,0.1); }}
        .card h3 {{ margin-top: 0; font-size: 1.1em; color: #1a2a6c; min-height: 3em; }}
        .tag {{ align-self: flex-start; background: #eef2ff; color: #1a2a6c; border: 1px solid #d9e2ff; border-radius: 4px; padding: 3px 8px; font-size: 0.72em; font-weight: 700; margin-bottom: 12px; }}
        .card p {{ font-size: 0.9em; color: #555; margin-bottom: 20px; }}
        .btn {{ margin-top: auto; display: inline-block; background: #1a2a6c; color: white; padding: 8px 16px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 0.9em; text-align: center; }}
        .btn:hover {{ background: #2a3a7c; }}
        footer {{ margin-top: 60px; text-align: center; color: #888; font-size: 0.9em; }}
    </style>
</head>
<body>
    <header>
        <h1>AI-Related Whitepapers</h1>
        <div class="subtitle">Research and development by Michael Rapoport, Polaritronics, Inc.</div>
    </header>
    <div class="support">
        <strong>Support ongoing AI research:</strong>
        Help fund continued experiments, writing, tooling, and publication through
        <a href="https://github.com/sponsors/michaelrapoport">GitHub Sponsors</a> or
        <a href="https://www.buymeacoffee.com/michaelrapoport">Buy Me a Coffee</a>.
    </div>
{''.join(sections)}
    <footer>
        &copy; 2026 Michael Rapoport, Polaritronics, Inc. All rights reserved.
    </footer>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--manifest", action="store_true")
    args = parser.parse_args()

    source_papers = collect_papers(args.limit)
    papers = merge_with_existing(source_papers)
    print(f"Selected {len(source_papers)} source papers; publishing {len(papers)} total pages including existing repository papers.")
    for category, subgroups in grouped(papers).items():
        total = sum(len(items) for items in subgroups.values())
        print(f"{category}: {total}")
        for subcategory, items in sorted(subgroups.items()):
            print(f"  - {subcategory}: {len(items)}")
    if args.manifest:
        print(json.dumps([
            {"title": p.title, "slug": p.slug, "category": p.category, "subcategory": p.subcategory, "source": str(p.source)}
            for p in papers
        ], indent=2))
    if not args.write:
        return

    for paper in source_papers:
        (REPO_ROOT / f"{paper.slug}.html").write_text(render_paper(paper), encoding="utf-8")
    (REPO_ROOT / "README.md").write_text(render_readme(papers), encoding="utf-8", newline="\n")
    (REPO_ROOT / "index.html").write_text(render_index(papers), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

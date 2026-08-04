#!/usr/bin/env python3
"""Migrate the three existing theology book skills to the v1 tag contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from book_to_skill.catalog import validate_manifest  # noqa: E402


# Labels are shared by every occurrence of a canonical tag.  Unlisted IDs get
# a deterministic English label from their kebab-case suffix.
TAG_LABELS: Dict[str, List[str]] = {
    "concept/anhypostasia": ["Anhypostasia", "Anhypostasie", "안위격론"],
    "concept/autopistia": ["Autopistia", "성경 자증성"],
    "concept/chalcedon": ["Chalcedon", "칼케돈"],
    "concept/christology": ["Christology", "Christologie", "그리스도론"],
    "concept/church": ["Church", "Ecclesiology", "교회론"],
    "concept/creation": ["Creation", "창조"],
    "concept/docetism": ["Docetism", "Doketismus", "가현설"],
    "concept/enhypostasia": ["Enhypostasia", "Enhypostasie", "함위격론"],
    "concept/eudokia": ["Eudokia", "기쁘신 뜻"],
    "concept/fall": ["Fall", "타락"],
    "concept/flood": ["Flood", "대홍수"],
    "concept/foedus-gratiae": ["Foedus Gratiae", "은혜언약"],
    "concept/foedus-operum": ["Foedus Operum", "행위언약"],
    "concept/genealogy": ["Genealogy", "족보"],
    "concept/ground-of-incarnation": ["Ground of Incarnation", "성육신의 근거"],
    "concept/imago-dei": ["Imago Dei", "하나님의 형상"],
    "concept/imputation": ["Imputation", "의의 전가"],
    "concept/incarnation": ["Incarnation", "Menschwerdung", "성육신"],
    "concept/justification": ["Justification", "칭의론"],
    "concept/mediator": ["Mediator", "Der Mittler", "중보자"],
    "concept/name-of-jesus": ["Name of Jesus", "예수 그리스도의 이름"],
    "concept/nephilim": ["Nephilim", "네피림"],
    "concept/noahic-covenant": ["Noahic Covenant", "노아 언약"],
    "concept/objective-justification": ["Objective Justification", "객관적 칭의"],
    "concept/pactum-salutis": ["Pactum Salutis", "구원협약"],
    "concept/peleg": ["Peleg", "벨렉"],
    "concept/primeval-history": ["Primeval History", "원역사"],
    "concept/revelation": ["Revelation", "계시"],
    "concept/sabbath": ["Sabbath", "안식일"],
    "concept/sacraments": ["Sacraments", "성례전"],
    "concept/sanctification": ["Sanctification", "성화"],
    "concept/scripture": ["Scripture", "성경론"],
    "concept/second-adam": ["Second Adam", "둘째 아담"],
    "concept/theology-proper": ["Theology Proper", "신론"],
    "concept/toledot": ["Toledot", "톨레돗"],
    "concept/true-humanity": ["True Humanity", "Der wahre Mensch", "참된 인간"],
    "concept/trinity": ["Trinity", "삼위일체"],
    "concept/virgin-birth": ["Virgin Birth", "Jungfrauengeburt", "동정녀 탄생"],
    "concept/violence": ["Violence", "폭력"],
    "framework/absolute-relative-ground": [
        "Absolute and Relative Ground",
        "절대적 근거와 상대적 근거",
    ],
    "framework/christocentric-reconstruction": [
        "Christocentric Reconstruction",
        "그리스도 중심적 재구성",
    ],
    "framework/church-dogmatics-architecture": [
        "Church Dogmatics Architecture",
        "교의학 건축학",
    ],
    "framework/conversational-theology": ["Conversational Theology", "대화적 신학"],
    "framework/federal-theology": ["Federal Theology", "연방신학"],
    "framework/incarnational-realism": ["Incarnational Realism", "성육신적 실재론"],
    "framework/layered-composition": ["Layered Composition", "문학적 층위 구성"],
    "framework/logos-sarx-exegesis": ["Logos-Sarx Exegesis", "로고스와 사르크스 주해"],
    "framework/post-priestly-redaction": ["Post-Priestly Redaction", "후기 제사장 편집"],
    "framework/priestly-non-priestly-redaction": [
        "Priestly and Non-Priestly Redaction",
        "제사장 및 비제사장 편집",
    ],
    "framework/priestly-writing": ["Priestly Writing", "제사장 문헌"],
    "framework/question-reversal": ["Question Reversal", "질문의 전회"],
    "framework/ramist-dichotomy": ["Ramist Dichotomy", "라무스적 이분법"],
    "framework/reasonable-orthodoxy": ["Reasonable Orthodoxy", "합리적 정통주의"],
    "framework/scholarly-narrator": ["Scholarly Narrator", "지혜로운 서술자"],
    "framework/widerspruch-versohnung": ["Widerspruch und Versöhnung", "모순과 화해"],
    "method/archive-research": ["Archive Research", "아카이브 연구"],
    "method/christological-exegesis": ["Christological Exegesis", "그리스도론적 주해"],
    "method/confessional-exegesis": ["Confessional Exegesis", "고백적 주해"],
    "method/cruciform-theology": ["Cruciform Theology", "십자가 신학"],
    "method/historical-theology": ["Historical Theology", "역사신학"],
    "method/literary-criticism": ["Literary Criticism", "문학비평"],
    "method/philological-analysis": ["Philological Analysis", "문헌학적 분석"],
    "method/source-criticism": ["Source Criticism", "자료비평"],
    "theme/ancient-near-eastern-context": [
        "Ancient Near Eastern Context",
        "고대 근동 배경",
    ],
    "theme/confessing-church": ["Confessing Church", "고백교회"],
    "theme/creation-order": ["Creation Order", "창조 질서"],
    "theme/dialectical-theology": ["Dialectical Theology", "변증법적 신학"],
    "theme/empire-critique": ["Empire Critique", "제국 비판"],
    "theme/human-ambivalence": ["Human Ambivalence", "인간 실존의 양면성"],
    "theme/modernity": ["Modernity", "근대성"],
    "theme/postwar-church": ["Postwar Church", "전후 교회"],
    "theme/reformed-orthodoxy": ["Reformed Orthodoxy", "개혁파 정통주의"],
}

PERSON_LABELS: Dict[str, List[str]] = {
    "amandus-polanus": ["Amandus Polanus", "아마두스 폴라누스"],
    "andreas-rivetus": ["Andreas Rivetus", "Rivetus"],
    "antonius-walaeus": ["Antonius Walaeus", "Walaeus"],
    "anselm-of-canterbury": ["Anselm of Canterbury", "Anselm", "안셀무스"],
    "david-friedrich-strauss": ["David Friedrich Strauss", "D. F. Strauss", "슈트라우스"],
    "friedrich-schleiermacher": ["Friedrich Schleiermacher", "슐라이어마허"],
    "georg-wilhelm-friedrich-hegel": ["G. W. F. Hegel", "Hegel", "헤겔"],
    "gerhard-von-rad": ["Gerhard von Rad", "von Rad"],
    "heinrich-heppe": ["Heinrich Heppe", "하인리히 헤페"],
    "jan-christian-gertz": ["Jan Christian Gertz", "Gertz"],
    "jean-alphonse-turretin": ["Jean-Alphonse Turretin", "J. A. Turretin", "J.A. Turretin"],
    "jean-ostervald": ["Jean Ostervald", "Ostervald"],
    "johannes-cocceius": ["Johannes Cocceius", "요하네스 코케이우스"],
    "johannes-polyander": ["Johannes Polyander", "Polyander"],
    "johannes-thysius": ["Johannes Thysius", "Thysius"],
    "john-calvin": ["John Calvin", "Calvin", "칼빈"],
    "karl-barth": ["Karl Barth", "칼 바르트"],
    "leontius-of-byzantium": ["Leontius of Byzantium", "Leontios von Byzanz", "레온티우스"],
    "martin-luther": ["Martin Luther", "Luther", "루터"],
    "samuel-werenfels": ["Samuel Werenfels", "Werenfels"],
    "soren-kierkegaard": ["Søren Kierkegaard", "키르케고르"],
}


def _display_label(identifier: str) -> str:
    value = identifier.split("/", 1)[-1].replace("-", " ")
    return " ".join(part.capitalize() for part in value.split())


def tag(identifier: str, relevance: str = "primary", basis: str = "explicit") -> dict:
    return {
        "id": identifier,
        "labels": list(TAG_LABELS.get(identifier, [_display_label(identifier)])),
        "relevance": relevance,
        "basis": basis,
    }


def _spec(spec: Any, default_relevance: str, default_basis: str) -> Tuple[str, str, str]:
    if isinstance(spec, str):
        return spec, default_relevance, default_basis
    if len(spec) == 2:
        return spec[0], spec[1], default_basis
    return spec[0], spec[1], spec[2]


def facet_ref(identifier: str, relevance: str = "primary", basis: str = "inferred") -> dict:
    return {"id": identifier, "relevance": relevance, "basis": basis}


def locus(spec: Any) -> dict:
    return facet_ref(*_spec(spec, "primary", "inferred"))


def scripture(spec: Any) -> dict:
    return facet_ref(*_spec(spec, "primary", "explicit"))


def person_ref(spec: Any) -> dict:
    identifier, relevance, basis = _spec(spec, "primary", "explicit")
    return {
        "id": identifier,
        "labels": list(PERSON_LABELS[identifier]),
        "relevance": relevance,
        "basis": basis,
    }


def tags(*specs: Any) -> List[dict]:
    result = []
    for spec in specs:
        result.append(tag(*_spec(spec, "primary", "explicit")))
    return result


def chapter(
    chapter_tags: Sequence[dict],
    *,
    loci: Sequence[Any] = (),
    scriptures: Sequence[Any] = (),
    persons: Sequence[Any] = (),
) -> dict:
    return {
        "tags": list(chapter_tags),
        "facets": {
            "loci": [locus(item) for item in loci],
            "scriptures": [scripture(item) for item in scriptures],
            "persons": [person_ref(item) for item in persons],
        },
    }


def book_facets(
    *,
    disciplines: Sequence[Any],
    loci: Sequence[Any],
    traditions: Sequence[Any],
) -> dict:
    return {
        "disciplines": [facet_ref(*_spec(item, "primary", "inferred")) for item in disciplines],
        "loci": [facet_ref(*_spec(item, "primary", "inferred")) for item in loci],
        "traditions": [facet_ref(*_spec(item, "primary", "inferred")) for item in traditions],
    }


GERTZ_LOCI = (
    ("biblical-studies/old-testament", "supporting"),
    ("biblical-studies/pentateuch", "supporting"),
    ("biblical-studies/primeval-history", "primary"),
)


BOOKS: Dict[str, dict] = {
    "brouwer-barth-orthodoxy": {
        "title": "Karl Barth and Post-Reformation Orthodoxy",
        "authors": ["Rinse H. Reeling Brouwer"],
        "lens": "theology",
        "tags": tags(
            ("theme/reformed-orthodoxy", "primary", "explicit"),
            ("theme/dialectical-theology", "supporting", "explicit"),
            ("concept/christology", "primary", "explicit"),
            ("concept/revelation", "supporting", "explicit"),
            ("concept/covenant", "supporting", "explicit"),
            ("concept/justification", "supporting", "explicit"),
            ("concept/church", "supporting", "explicit"),
            ("framework/church-dogmatics-architecture", "primary", "explicit"),
        ),
        "facets": book_facets(
            disciplines=(("theology/historical-theology", "primary"), ("theology/systematic-theology", "supporting")),
            loci=(
                ("dogmatics/christology", "primary"),
                ("dogmatics/revelation", "supporting"),
                ("dogmatics/soteriology", "supporting"),
                ("dogmatics/ecclesiology", "supporting"),
            ),
            traditions=(
                ("reformed", "primary", "inferred"),
                ("reformed-orthodoxy", "primary", "explicit"),
                ("dialectical-theology", "supporting", "inferred"),
            ),
        ),
        "chapters": {
            "ch00": chapter(
                tags(
                    "theme/reformed-orthodoxy",
                    "method/archive-research",
                    "method/philological-analysis",
                    "method/historical-theology",
                    "framework/conversational-theology",
                    ("concept/revelation", "supporting"),
                    ("theme/modernity", "supporting"),
                ),
                loci=(("dogmatics/revelation", "primary"),),
                persons=(
                    "karl-barth",
                    ("heinrich-heppe", "primary"),
                    ("amandus-polanus", "supporting"),
                    ("johannes-cocceius", "supporting"),
                    ("friedrich-schleiermacher", "supporting"),
                ),
            ),
            "ch01": chapter(
                tags(
                    "theme/reformed-orthodoxy",
                    "framework/ramist-dichotomy",
                    "concept/divine-attributes",
                    "concept/theology-proper",
                    ("concept/trinity", "supporting"),
                    ("concept/christology", "supporting"),
                ),
                loci=(("dogmatics/theology-proper", "primary"), ("dogmatics/christology", "supporting")),
                persons=("amandus-polanus", "karl-barth"),
            ),
            "ch02": chapter(
                tags(
                    "concept/scripture",
                    "concept/autopistia",
                    "concept/trinity",
                    "concept/predestination",
                    "concept/christology",
                    ("concept/incarnation", "supporting"),
                    ("concept/revelation", "supporting"),
                    ("concept/creation-order", "mention"),
                ),
                loci=(
                    ("dogmatics/revelation", "primary"),
                    ("dogmatics/theology-proper", "supporting"),
                    ("dogmatics/christology", "primary"),
                    ("dogmatics/soteriology", "primary"),
                ),
                persons=(
                    "karl-barth",
                    "johannes-polyander",
                    "andreas-rivetus",
                    "antonius-walaeus",
                    "johannes-thysius",
                ),
            ),
            "ch03": chapter(
                tags(
                    "concept/covenant",
                    "concept/foedus-operum",
                    "concept/foedus-gratiae",
                    "concept/pactum-salutis",
                    "framework/federal-theology",
                    ("concept/providence", "supporting"),
                    ("concept/christology", "supporting"),
                ),
                loci=(("dogmatics/soteriology", "primary"), ("dogmatics/christology", "supporting")),
                persons=("johannes-cocceius", "karl-barth"),
            ),
            "ch04": chapter(
                tags(
                    "concept/church",
                    "concept/sacraments",
                    "concept/baptism",
                    "concept/church-office",
                    "theme/reformed-orthodoxy",
                    ("concept/christology", "supporting"),
                    ("concept/grace", "supporting"),
                ),
                loci=(("dogmatics/ecclesiology", "primary"), ("dogmatics/sacramentology", "supporting")),
                persons=("heinrich-heppe", "karl-barth"),
            ),
            "ch05": chapter(
                tags(
                    "concept/justification",
                    "concept/imputation",
                    "concept/objective-justification",
                    "concept/sanctification",
                    "framework/reasonable-orthodoxy",
                    "theme/reformed-orthodoxy",
                    ("concept/christology", "supporting"),
                    ("concept/union-with-christ", "supporting"),
                ),
                loci=(("dogmatics/soteriology", "primary"), ("dogmatics/christology", "supporting")),
                persons=(
                    "karl-barth",
                    "jean-alphonse-turretin",
                    "jean-ostervald",
                    "samuel-werenfels",
                ),
            ),
            "ch06": chapter(
                tags(
                    "framework/church-dogmatics-architecture",
                    "concept/prolegomena",
                    "concept/predestination",
                    "concept/ethics",
                    "concept/christology",
                    "concept/revelation",
                    "theme/reformed-orthodoxy",
                    ("method/historical-theology", "supporting"),
                ),
                loci=(
                    ("dogmatics/revelation", "primary"),
                    ("dogmatics/theology-proper", "primary"),
                    ("dogmatics/christology", "primary"),
                    ("dogmatics/soteriology", "supporting"),
                ),
                persons=("karl-barth", "heinrich-heppe"),
            ),
        },
    },
    "gertz-genesis-1-11": {
        "title": "Genesis 1–11",
        "authors": ["Jan Christian Gertz"],
        "lens": "theology",
        "tags": tags(
            ("concept/primeval-history", "primary", "explicit"),
            ("concept/creation", "primary", "explicit"),
            ("concept/fall", "primary", "explicit"),
            ("concept/flood", "primary", "explicit"),
            ("concept/genealogy", "primary", "explicit"),
            ("method/source-criticism", "primary", "explicit"),
            ("method/literary-criticism", "primary", "explicit"),
            ("theme/ancient-near-eastern-context", "supporting", "explicit"),
        ),
        "facets": book_facets(
            disciplines=(
                ("theology/biblical-studies", "primary", "inferred"),
                ("theology/exegesis", "primary", "inferred"),
                ("humanities/ancient-near-eastern-studies", "supporting", "inferred"),
            ),
            loci=(
                ("biblical-studies/old-testament", "primary", "inferred"),
                ("biblical-studies/pentateuch", "primary", "inferred"),
                ("biblical-studies/primeval-history", "primary", "explicit"),
            ),
            traditions=(
                ("historical-critical", "primary", "inferred"),
                ("old-testament-exegesis", "primary", "inferred"),
                ("priestly-tradition", "supporting", "explicit"),
            ),
        ),
        "chapters": {
            "ch00": chapter(
                tags(
                    "concept/primeval-history",
                    "method/source-criticism",
                    "method/literary-criticism",
                    "framework/layered-composition",
                    "theme/ancient-near-eastern-context",
                    "concept/human-ambivalence",
                    ("concept/toledot", "supporting"),
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 1:1-11:26", "primary"),),
                persons=("jan-christian-gertz", ("gerhard-von-rad", "supporting")),
            ),
            "ch01": chapter(
                tags(
                    "concept/creation",
                    "concept/imago-dei",
                    "concept/sabbath",
                    "framework/priestly-writing",
                    "method/source-criticism",
                    "theme/creation-order",
                    ("theme/ancient-near-eastern-context", "supporting"),
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 1:1-2:3", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch02": chapter(
                tags(
                    "concept/creation",
                    "concept/fall",
                    "concept/human-finitude",
                    "concept/etiology",
                    "framework/scholarly-narrator",
                    "method/source-criticism",
                    ("theme/ancient-near-eastern-context", "supporting"),
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 2:4-3:24", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch03": chapter(
                tags(
                    "concept/cain-and-abel",
                    "concept/violence",
                    "concept/civilization",
                    "concept/human-ambivalence",
                    "framework/scholarly-narrator",
                    "method/source-criticism",
                    ("concept/genealogy", "supporting"),
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 4:1-26", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch04": chapter(
                tags(
                    "concept/genealogy",
                    "concept/toledot",
                    "concept/chronology",
                    "concept/enoch",
                    "concept/human-finitude",
                    "framework/priestly-writing",
                    "method/source-criticism",
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 5:1-32", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch05": chapter(
                tags(
                    "concept/divine-beings",
                    "concept/nephilim",
                    "concept/human-finitude",
                    "framework/post-priestly-redaction",
                    "method/source-criticism",
                    "theme/ancient-near-eastern-context",
                    ("concept/creation-order", "supporting"),
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 6:1-4", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch06": chapter(
                tags(
                    "concept/flood",
                    "concept/noahic-covenant",
                    "concept/rainbow-covenant",
                    "concept/creation-order",
                    "framework/priestly-non-priestly-redaction",
                    "method/source-criticism",
                    "theme/ancient-near-eastern-context",
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 6:5-9:17", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch07": chapter(
                tags(
                    "concept/noah",
                    "concept/wine",
                    "concept/curse-of-canaan",
                    "concept/honor-shame",
                    "concept/human-ambivalence",
                    "framework/post-priestly-redaction",
                    "method/source-criticism",
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 9:18-29", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch08": chapter(
                tags(
                    "concept/table-of-nations",
                    "concept/ethnography",
                    "concept/peleg",
                    "concept/genealogy",
                    "concept/empire",
                    "framework/priestly-writing",
                    "method/literary-criticism",
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 10:1-32", "primary"),),
                persons=("jan-christian-gertz",),
            ),
            "ch09": chapter(
                tags(
                    "concept/babel",
                    "concept/language-dispersion",
                    "concept/human-pride",
                    "concept/city",
                    "framework/post-priestly-redaction",
                    "method/literary-criticism",
                    "theme/empire-critique",
                ),
                loci=GERTZ_LOCI,
                scriptures=(
                    ("Gen 11:1-9", "primary"),
                    ("Gen 1:28", "supporting"),
                    ("Gen 9:1", "supporting"),
                    ("Gen 12:1-3", "supporting"),
                ),
                persons=("jan-christian-gertz",),
            ),
            "ch10": chapter(
                tags(
                    "concept/genealogy",
                    "concept/toledot",
                    "concept/chronology",
                    "concept/primeval-history",
                    "framework/priestly-writing",
                    "method/source-criticism",
                    ("concept/creation-order", "supporting"),
                ),
                loci=GERTZ_LOCI,
                scriptures=(("Gen 11:10-26", "primary"), ("Gen 12:1-3", "supporting")),
                persons=("jan-christian-gertz",),
            ),
        },
    },
    "heinrich-vogel-christologie": {
        "title": "Christologie (Gesammelte Werke Bd. 5)",
        "authors": ["Heinrich Vogel"],
        "lens": "theology",
        "tags": tags(
            ("concept/christology", "primary", "explicit"),
            ("concept/incarnation", "primary", "explicit"),
            ("concept/true-humanity", "primary", "explicit"),
            ("concept/mediator", "supporting", "explicit"),
            ("concept/anhypostasia", "primary", "explicit"),
            ("concept/enhypostasia", "primary", "explicit"),
            ("theme/dialectical-theology", "supporting", "explicit"),
            ("theme/confessing-church", "supporting", "explicit"),
        ),
        "facets": book_facets(
            disciplines=(("theology/systematic-theology", "primary", "inferred"), ("theology/historical-theology", "supporting", "inferred")),
            loci=(
                ("dogmatics/christology", "primary", "inferred"),
                ("dogmatics/soteriology", "supporting", "inferred"),
                ("dogmatics/anthropology", "supporting", "inferred"),
            ),
            traditions=(
                ("reformed", "supporting", "explicit"),
                ("confessing-church", "primary", "explicit"),
                ("dialectical-theology", "primary", "inferred"),
            ),
        ),
        "chapters": {
            "ch00": chapter(
                tags(
                    "concept/christology",
                    "concept/revelation",
                    "concept/confession",
                    "theme/confessing-church",
                    "theme/postwar-church",
                    "method/confessional-exegesis",
                    ("concept/faith", "supporting"),
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/revelation", "supporting")),
                scriptures=(("Matt 16:16-17", "primary"), ("Eph 3:19", "supporting")),
                persons=(("karl-barth", "supporting"),),
            ),
            "ch01": chapter(
                tags(
                    "framework/question-reversal",
                    "concept/confession",
                    "concept/revelation",
                    "concept/faith",
                    "concept/paradox",
                    "theme/confessing-church",
                    "theme/dialectical-theology",
                    "method/confessional-exegesis",
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/revelation", "primary")),
                scriptures=(("Matt 16:13-17", "primary"), ("2 Cor 5:19", "supporting"), ("Luke 7:19", "supporting")),
                persons=(
                    "karl-barth",
                    ("soren-kierkegaard", "supporting"),
                    ("david-friedrich-strauss", "supporting"),
                    ("friedrich-schleiermacher", "supporting"),
                ),
            ),
            "ch02": chapter(
                tags(
                    "concept/name-of-jesus",
                    "concept/jesus-christ",
                    "concept/christology",
                    "concept/salvation",
                    "framework/incarnational-realism",
                    "method/christological-exegesis",
                    ("concept/confession", "supporting"),
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/soteriology", "supporting")),
                scriptures=(("Matt 1:21", "primary"), ("Phil 2:9-11", "primary"), ("Acts 4:12", "supporting"), ("Isa 53:1-12", "supporting")),
            ),
            "ch03": chapter(
                tags(
                    "concept/incarnation",
                    "concept/eudokia",
                    "concept/ground-of-incarnation",
                    "concept/grace",
                    "framework/absolute-relative-ground",
                    "theme/dialectical-theology",
                    "method/christological-exegesis",
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/soteriology", "supporting")),
                scriptures=(("Eph 1:5", "primary"), ("Eph 1:9", "primary"), ("John 3:16", "supporting"), ("Rom 5:8", "supporting")),
                persons=(("anselm-of-canterbury", "supporting"), ("john-calvin", "supporting"), ("karl-barth", "supporting")),
            ),
            "ch04": chapter(
                tags(
                    "concept/incarnation",
                    "concept/logos",
                    "concept/hypostatic-union",
                    "concept/virgin-birth",
                    "concept/docetism",
                    "concept/true-humanity",
                    "framework/logos-sarx-exegesis",
                    "method/christological-exegesis",
                ),
                loci=(("dogmatics/christology", "primary"),),
                scriptures=(("John 1:14", "primary"),),
                persons=(("martin-luther", "supporting"), ("john-calvin", "supporting")),
            ),
            "ch05": chapter(
                tags(
                    "concept/incarnation",
                    "concept/paradox",
                    "concept/reconciliation",
                    "concept/cross",
                    "concept/faith",
                    "framework/widerspruch-versohnung",
                    "method/cruciform-theology",
                    "theme/dialectical-theology",
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/soteriology", "supporting")),
                scriptures=(("1 Cor 1:23", "primary"), ("1 Cor 1:24", "supporting"), ("2 Cor 5:18", "supporting")),
                persons=(("georg-wilhelm-friedrich-hegel", "supporting"), ("soren-kierkegaard", "supporting"), ("martin-luther", "supporting")),
            ),
            "ch06": chapter(
                tags(
                    "concept/mediator",
                    "concept/incarnation",
                    "concept/hypostatic-union",
                    "concept/chalcedon",
                    "concept/christology",
                    "concept/true-humanity",
                    "theme/dialectical-theology",
                ),
                loci=(("dogmatics/christology", "primary"),),
                scriptures=(("1 Tim 2:5", "primary"), ("Heb 8:6", "supporting"), ("Heb 9:15", "supporting"), ("Gal 3:20", "supporting")),
            ),
            "ch07": chapter(
                tags(
                    "concept/true-humanity",
                    "concept/anhypostasia",
                    "concept/enhypostasia",
                    "concept/second-adam",
                    "concept/hypostatic-union",
                    "concept/christology",
                    "theme/dialectical-theology",
                    ("concept/faith", "supporting"),
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/anthropology", "supporting")),
                scriptures=(("Heb 4:15", "primary"), ("Rom 5:12-21", "supporting"), ("1 Cor 15:45-47", "supporting"), ("Heb 2:14", "supporting"), ("Heb 2:17", "supporting")),
                persons=(("leontius-of-byzantium", "supporting"), ("john-calvin", "supporting")),
            ),
            "ch08": chapter(
                tags(
                    "concept/ecce-homo",
                    "concept/true-humanity",
                    "concept/confession",
                    "concept/holy-spirit-testimony",
                    "concept/christology",
                    "theme/confessing-church",
                    "theme/postwar-church",
                    "method/confessional-exegesis",
                ),
                loci=(("dogmatics/christology", "primary"), ("dogmatics/pneumatology", "supporting")),
                scriptures=(("John 19:5", "primary"), ("Matt 16:17", "supporting"), ("1 Cor 12:3", "supporting")),
            ),
        },
    },
}

CHAPTER_FILENAME_RE = re.compile(r"^(ch[0-9]+)-([a-z0-9][a-z0-9._-]*)\.md$")
CHAPTER_HEADING_RE = re.compile(r"^# Chapter ([0-9]+): (.+?)\s*$")


def _split_skill_frontmatter(text: str, path: Path) -> Tuple[str, str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: SKILL.md has no YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"{path}: unterminated SKILL.md frontmatter") from exc
    name_line = next((line for line in lines[1:end] if line.startswith("name:")), None)
    description_line = next((line for line in lines[1:end] if line.startswith("description:")), None)
    if name_line is None or description_line is None:
        raise ValueError(f"{path}: frontmatter must contain name and description")
    body = "\n".join(lines[end + 1 :])
    if text.endswith("\n"):
        body += "\n"
    return name_line, description_line, body


def _metadata_lines(book: Mapping[str, Any]) -> List[str]:
    tag_ids = [ref["id"] for ref in book["tags"]]
    loci_ids = [ref["id"] for ref in book["facets"]["loci"]]
    tick = chr(96)
    return [
        "## Book Metadata",
        "",
        f"- **Authors:** {', '.join(book['authors'])}",
        f"- **Lens:** {book['lens']}",
        f"- **Tags:** {' '.join('#' + identifier for identifier in tag_ids)}",
        f"- **Loci:** {', '.join(tick + identifier + tick for identifier in loci_ids)}",
    ]


def _replace_book_metadata(text: str, book: Mapping[str, Any]) -> str:
    lines = text.splitlines()
    metadata = _metadata_lines(book)
    start = next((index for index, line in enumerate(lines) if line.strip() == "## Book Metadata"), None)
    if start is not None:
        end = start + len(metadata)
        if lines[start:end] != metadata:
            raise ValueError(f"{book['id']}: existing Book Metadata section is not owned by this migration")
        if end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
    heading = next((index for index, line in enumerate(lines) if line.startswith("# ") and not line.startswith("## ")), None)
    if heading is None:
        raise ValueError(f"{book['id']}: SKILL.md has no top-level heading")
    after_heading = heading + 1
    while after_heading < len(lines) and not lines[after_heading].strip():
        after_heading += 1
    result = lines[: heading + 1] + [""] + metadata + [""] + lines[after_heading:]
    return "\n".join(result).rstrip("\n") + "\n"


def _normalize_skill(text: str, path: Path, book: Mapping[str, Any]) -> str:
    name_line, description_line, body = _split_skill_frontmatter(text, path)
    expected_name = f"name: {book['id']}"
    if name_line.strip() != expected_name:
        raise ValueError(f"{path}: expected {expected_name!r}, found {name_line!r}")
    body = body.lstrip("\n")
    normalized = "---\n" + name_line + "\n" + description_line + "\n---\n\n" + body
    return _replace_book_metadata(normalized, book)


def _chapter_frontmatter(chapter_data: Mapping[str, Any], book_id: str) -> str:
    lines = [
        "---",
        f"chapter: {chapter_data['number']}",
        f"chapter-id: {chapter_data['id']}",
        f"book-id: {book_id}",
        f"title: {json.dumps(chapter_data['title'], ensure_ascii=False)}",
        "tags:",
    ]
    lines.extend(f"  - {ref['id']}" for ref in chapter_data["tags"])
    lines.append("loci:")
    lines.extend(f"  - {ref['id']}" for ref in chapter_data["facets"]["loci"])
    lines.append("scriptures:")
    lines.extend(f"  - {json.dumps(ref['id'], ensure_ascii=False)}" for ref in chapter_data["facets"]["scriptures"])
    lines.append("persons:")
    lines.extend(f"  - {ref['id']}" for ref in chapter_data["facets"]["persons"])
    lines.extend(["---", ""])
    return "\n".join(lines)


def _remove_existing_chapter_frontmatter(text: str, path: Path) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines()
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"{path}: unterminated chapter frontmatter") from exc
    existing = "\n".join(lines[: end + 1])
    if "chapter-id:" not in existing or "book-id:" not in existing:
        raise ValueError(f"{path}: refusing to replace unknown existing frontmatter")
    body = "\n".join(lines[end + 1 :])
    if text.endswith("\n"):
        body += "\n"
    return body.lstrip("\n")


def _chapter_records(book_id: str, book_dir: Path) -> List[dict]:
    configured = BOOKS[book_id]["chapters"]
    chapter_dir = book_dir / "chapters"
    if not chapter_dir.is_dir():
        raise ValueError(f"{book_dir}: chapters directory is missing")
    records: List[dict] = []
    seen_ids = set()
    for path in sorted(chapter_dir.glob("*.md")):
        if path.is_symlink():
            raise ValueError(f"{path}: chapter symlink is not allowed")
        match = CHAPTER_FILENAME_RE.fullmatch(path.name)
        if match is None:
            raise ValueError(f"{path}: expected chNN-slug.md filename")
        chapter_id = match.group(1)
        if chapter_id in seen_ids:
            raise ValueError(f"{book_id}: duplicate chapter id {chapter_id}")
        seen_ids.add(chapter_id)
        text = path.read_text(encoding="utf-8")
        body = _remove_existing_chapter_frontmatter(text, path)
        first_line = body.splitlines()[0] if body.splitlines() else ""
        heading_match = CHAPTER_HEADING_RE.match(first_line)
        if heading_match is None:
            raise ValueError(f"{path}: first body line must be a Chapter heading")
        number = int(heading_match.group(1))
        if chapter_id != f"ch{number:02d}":
            raise ValueError(f"{path}: chapter id {chapter_id} does not match number {number}")
        if chapter_id not in configured:
            raise ValueError(f"{book_id}: no tagging map for {chapter_id}")
        slug = match.group(2).replace("_", "-").lower()
        records.append(
            {
                "id": chapter_id,
                "number": number,
                "slug": slug,
                "title": heading_match.group(2).strip(),
                "path": f"chapters/{path.name}",
                "tags": configured[chapter_id]["tags"],
                "facets": configured[chapter_id]["facets"],
                "_path": path,
                "_body": body,
            }
        )
    if set(configured) != seen_ids:
        missing = sorted(set(configured) - seen_ids)
        extra = sorted(seen_ids - set(configured))
        raise ValueError(f"{book_id}: chapter map mismatch; missing={missing}, extra={extra}")
    records.sort(key=lambda item: item["number"])
    return records


def build_migration_data(books_root: Path) -> List[Tuple[Path, dict, List[dict]]]:
    results = []
    for book_id in sorted(BOOKS):
        book_dir = books_root / book_id
        if not book_dir.is_dir() or book_dir.is_symlink():
            raise ValueError(f"{book_dir}: expected a real book directory")
        config = BOOKS[book_id]
        book = {
            "id": book_id,
            "title": config["title"],
            "authors": list(config["authors"]),
            "lens": config["lens"],
            "tags": config["tags"],
            "facets": config["facets"],
        }
        records = _chapter_records(book_id, book_dir)
        manifest = {
            "schema_version": 1,
            "book": book,
            "chapters": [
                {key: value for key, value in record.items() if not key.startswith("_")}
                for record in records
            ],
        }
        errors = validate_manifest(manifest, book_dir)
        if errors:
            raise ValueError("\n".join(errors))
        results.append((book_dir, manifest, records))
    return results


def _write_migration(data: List[Tuple[Path, dict, List[dict]]], force: bool) -> int:
    changed = 0
    for book_dir, manifest, records in data:
        book_id = manifest["book"]["id"]
        skill_path = book_dir / "SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")
        normalized_skill = _normalize_skill(skill_text, skill_path, manifest["book"])
        if normalized_skill != skill_text:
            skill_path.write_text(normalized_skill, encoding="utf-8")
            changed += 1
        for record in records:
            path = record["_path"]
            original = path.read_text(encoding="utf-8")
            projected = _chapter_frontmatter(record, book_id) + record["_body"]
            if projected != original:
                path.write_text(projected, encoding="utf-8")
                changed += 1
        manifest_path = book_dir / "book-index.json"
        payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        if manifest_path.exists() and not force:
            existing = manifest_path.read_text(encoding="utf-8")
            if existing != payload:
                raise ValueError(f"{manifest_path}: differs; rerun with --force")
        elif not manifest_path.exists() or force:
            manifest_path.write_text(payload, encoding="utf-8")
            changed += 1
    return changed


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true", help="validate without writing")
    parser.add_argument("--force", action="store_true", help="replace differing existing manifests")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        data = build_migration_data(args.books_root.resolve())
        books = len(data)
        chapters = sum(len(records) for _, _, records in data)
        if args.check:
            print(f"Migration check passed: books={books}, chapters={chapters}")
        else:
            changed = _write_migration(data, args.force)
            print(f"Migration written: books={books}, chapters={chapters}, changed_files={changed}")
    except (OSError, ValueError, KeyError) as exc:
        print(f"ERROR existing book migration failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

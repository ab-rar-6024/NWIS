from __future__ import annotations

import pytest

from nwis.extraction.documents import canonical_formation
from nwis.extraction.events import extract_events, parse_depth, split_sentences


def ev(text: str, day_depth: float | None = 3000.0):
    return extract_events(split_sentences(text), day_depth=day_depth)


def test_depth_formats():
    assert parse_depth("Partial losses at 2,371 m in Kopili") == 2371
    assert parse_depth("stuck at 2371m") == 2371
    assert parse_depth("Drilled to 3040 mMD") == 3040
    assert parse_depth("reached 500 mts") == 500
    assert parse_depth("ROP 48.9 m/hr, loss 12 m3/hr") is None  # rates are not depths


def test_mud_loss_with_quantities_and_outcome():
    e = ev("Partial losses encountered at 3,299 m while drilling 8-1/2\" hole in Sylhet Limestone. Loss rate 12.5 m3/hr. "
           "Pumped 15 m3 LCM pill (30 ppb fine nut plug). Losses reduced to 2.1 m3/hr. NPT 6.5 hrs.")
    assert len(e) == 1
    x = e[0]
    assert x.type == "mud_loss" and x.md == 3299 and x.depth_source == "explicit"
    assert x.details["rate_m3h"] == 12.5 and x.details["residual_m3h"] == 2.1
    assert x.details["lcm_vol_m3"] == 15 and x.details["lcm_ppb"] == 30
    assert "lcm_pill" in x.mitigations and x.outcome == "reduced" and x.npt_h == 6.5


@pytest.mark.parametrize("text", [
    "No losses observed while drilling this section.",
    "Mud losses: nil.",
    "Flow check at 3,050 m negative.",
    "Well stable, no kick indicators.",
    "Kept 30 m3 LCM pill ready as precaution against losses.",
    "No tight hole or overpull noted on connections.",
    "Torque and drag within normal range.",
    "Recommend having LCM pills ready before entering the Sylhet; mud losses recur in this interval.",
])
def test_negations_and_contingencies_are_not_events(text):
    assert ev(text) == []


def test_kick_cluster_is_one_event():
    e = ev("Well flowing at 3,036 m. Shut in well; SIDPP 22 bar, SICP 30 bar, pit gain 2.4 m3. "
           "Killed well using Driller's method; MW raised from 1.29 to 1.41 SG. Well stable after kill, resumed drilling. NPT 14.7 hrs.")
    assert len(e) == 1
    x = e[0]
    assert x.type == "kick" and x.md == 3036
    assert x.details["gain_m3"] == 2.4 and x.details["sidpp_bar"] == 22 and x.details["mw1"] == 1.41
    assert x.outcome == "controlled" and x.npt_h == 14.7


def test_stuck_pipe_backoff_is_not_freed():
    e = ev("Pipe stuck at 2,192 m (pack-off); max overpull 35 t. Unable to free pipe; ran free-point and backed off near 2,195 m leaving BHA in hole.")
    assert len(e) == 1 and e[0].type == "stuck_pipe"
    assert e[0].outcome == "fish_left" and "backoff" in e[0].mitigations
    assert e[0].details["overpull_t"] == 35 and e[0].details["mechanism"] == "pack-off"


def test_two_different_events_in_one_paragraph_are_separated():
    e = ev("High torque (peak 24.5 kNm) recorded at 3,250 m in the Kopili Shale; RPM reduced and hole cleaned. NPT 6.6 hrs. "
           "A gas kick was taken at 3410 m in the Kopili Shale (pit gain 3.9 m3).")
    assert [x.type for x in e] == ["torque_spike", "kick"]
    assert e[0].md == 3250 and e[1].md == 3410


def test_missing_depth_falls_back_to_day_depth_with_lower_confidence():
    with_depth = ev("Partial losses at 3,299 m, loss rate 8 m3/hr.")[0]
    no_depth = ev("Partial losses noted while drilling ahead, loss rate 8 m3/hr.", day_depth=3350.0)[0]
    assert no_depth.depth_source == "day" and no_depth.md == 3350.0
    assert no_depth.confidence < with_depth.confidence


def test_ocr_style_text_without_spaces_still_parses():
    e = ev("Lostcirculation(partial)wasexperiencedat2058mtsintheTipamSandstonewithamaximumlossof6.2m3/hr;curedwithLCMpills.NPT1.6hrs.")
    assert len(e) == 1 and e[0].type == "mud_loss" and e[0].md == 2058
    assert e[0].details.get("severity") == "partial"


def test_sentence_split_after_unit_abbreviations():
    s = split_sentences("Estimated pore pressure 1.45 SG. Increased MW from 1.19 to 1.31 SG. NPT 3 hrs.")
    assert len(s) == 3


def test_canonical_formation_repairs_ocr_damage():
    assert canonical_formation("TipamSandstone") == "Tipam Sandstone"
    assert canonical_formation("Sylhet Limest0ne") == "Sylhet Limestone"
    assert canonical_formation("Unmapped Fm") == "Unmapped Fm"

"""Every sentence the phone can say for every registry client must have a Henry clip in the built bundle (owner audio
gap: Walter's 'Go to the main bedroom.' fell back to the system voice). Skipped only when the bundle has no audio dir."""
import os
from pathlib import Path
import pytest
from ember_staff import db, pregen, config


def test_swift_spoken_strings_are_collected():
    strings = pregen.swift_spoken_strings()
    for must in ["Which way is the smoke?", "Which way is the new fire?", "Power is back.",
                 "This card does not match the phone's plan. Ask staff for a new card.",
                 "No safe road left. Stay in the open, away from trees and cars. Call 911 and read them this location."]:
        assert must in strings, must


def test_every_client_sentence_has_a_clip(sample):
    audio = config.bundle_dir(config.county()) / "audio"
    clips = {p.stem for p in audio.glob("*.mp3")} if audio.is_dir() else set()
    if not clips:
        pytest.skip("bundle has no recorded audio")
    missing = {}
    for cid in sample:
        row = db.get(cid)
        for text in pregen.collect(row):
            if pregen.hashing.clip_key(text) not in clips:
                missing[text] = cid
    assert not missing, f"{len(missing)} sentences without a clip, e.g. {list(missing)[:5]}"

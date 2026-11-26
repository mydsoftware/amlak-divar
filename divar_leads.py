# -*- coding: utf-8 -*-
"""تحلیل محلی آگهی‌های عمومی دیوار برای کشف سرنخ فروش؛ بدون استخراج اطلاعات تماس."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


INTENT_KEYWORDS = {
    "BUY": ("خریدارم", "خریدار هستم", "متقاضی خرید", "قصد خرید", "دنبال خرید", "خریدار آپارتمان", "خریدار زمین"),
    "SELL": ("فروش", "فروشی", "فروش فوری", "فروشنده", "به فروش میرسد", "به فروش می‌رسد", "واگذار میشود", "واگذار می‌شود"),
    "RENT": ("اجاره", "رهن و اجاره", "اجاره داده میشود", "اجاره داده می‌شود", "مستاجر", "مستأجر"),
    "LEASE": ("مستاجر میپذیریم", "مستأجر می‌پذیریم", "رهن کامل", "رهن داده میشود", "رهن داده می‌شود"),
    "SERVICE_SEEKER": ("نیازمند", "دنبال نصاب", "دنبال تعمیرکار", "درخواست خدمات", "خدمات میخواهم", "خدمات می‌خواهم"),
    "SERVICE_PROVIDER": ("خدمات", "انجام میدهیم", "انجام می‌دهیم", "تعمیرات", "نصب و راه اندازی", "نصب و راه‌اندازی"),
}

DEFAULT_NEGATIVE = ("استخدام", "استخدامی", "استخدام می‌کنیم", "استخدام میکنیم", "کارگر", "همکاری در فروش")


def normalize_fa(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    text = re.sub(r"[\u064b-\u065f\u0670]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


@dataclass
class BusinessProfile:
    name: str
    industry: str = ""
    positive_keywords: List[str] = field(default_factory=list)
    negative_keywords: List[str] = field(default_factory=list)
    target_categories: List[str] = field(default_factory=list)
    target_districts: List[str] = field(default_factory=list)
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    weights: Dict[str, int] = field(default_factory=lambda: {
        "keyword": 45, "category": 20, "district": 15, "price": 20
    })


@dataclass
class LeadAnalysis:
    intent: str
    score: int
    confidence: str
    matched_signals: List[str]
    excluded_signals: List[str]
    requires_human_review: bool = True

    def as_dict(self) -> dict:
        return {
            "intent": self.intent,
            "score": self.score,
            "confidence": self.confidence,
            "matched_signals": self.matched_signals,
            "excluded_signals": self.excluded_signals,
            "requires_human_review": self.requires_human_review,
        }


def detect_intent(title: str, description: str = "") -> tuple[str, List[str]]:
    text = normalize_fa(f"{title} {description}")
    # ترتیب اولویت مانع از اشتباه گرفتن آگهی «ملک برای اجاره» با درخواست اجاره می‌شود.
    for intent in ("BUY", "SERVICE_SEEKER", "LEASE", "RENT", "SELL", "SERVICE_PROVIDER"):
        hits = [term for term in INTENT_KEYWORDS[intent] if normalize_fa(term) in text]
        if hits:
            return intent, hits[:5]
    return "UNKNOWN", []


def analyze_listing(
    listing: dict,
    profile: BusinessProfile,
) -> LeadAnalysis:
    title = normalize_fa(listing.get("title", ""))
    description = normalize_fa(listing.get("description", ""))
    text = f"{title} {description}".strip()
    category = normalize_fa(listing.get("category", ""))
    district = normalize_fa(listing.get("district", ""))
    intent, intent_hits = detect_intent(title, description)

    matched: List[str] = []
    excluded: List[str] = []
    negative_hits = [word for word in profile.negative_keywords + list(DEFAULT_NEGATIVE)
                     if normalize_fa(word) in text]
    if negative_hits:
        excluded.extend(f"negative:{word}" for word in negative_hits)

    positive_hits = [word for word in profile.positive_keywords if normalize_fa(word) in text]
    if positive_hits:
        matched.extend(f"keyword:{word}" for word in positive_hits)

    category_hits = [value for value in profile.target_categories if normalize_fa(value) in category]
    if category_hits:
        matched.extend(f"category:{value}" for value in category_hits)

    district_hits = [value for value in profile.target_districts if normalize_fa(value) in district]
    if district_hits:
        matched.extend(f"district:{value}" for value in district_hits)

    price = listing.get("price")
    price_match = False
    if isinstance(price, (int, float)):
        price_match = (
            (profile.min_price is None or price >= profile.min_price)
            and (profile.max_price is None or price <= profile.max_price)
        )
        if price_match and (profile.min_price is not None or profile.max_price is not None):
            matched.append("price:within_range")

    weights = profile.weights
    total = sum(max(0, int(v)) for v in weights.values()) or 1
    earned = 0
    if positive_hits:
        earned += max(0, int(weights.get("keyword", 0)))
    if category_hits:
        earned += max(0, int(weights.get("category", 0)))
    if district_hits:
        earned += max(0, int(weights.get("district", 0)))
    if price_match and (profile.min_price is not None or profile.max_price is not None):
        earned += max(0, int(weights.get("price", 0)))

    score = round(100 * earned / total)
    if negative_hits:
        score = max(0, score - min(60, 25 * len(negative_hits)))
    if intent == "UNKNOWN":
        score = min(score, 35)
    if not text:
        score = 0

    evidence_count = len(positive_hits) + len(category_hits) + len(district_hits)
    confidence = "HIGH" if evidence_count >= 3 else "MEDIUM" if evidence_count == 2 else "LOW"
    if not text or not matched:
        confidence = "LOW"

    return LeadAnalysis(
        intent=intent,
        score=max(0, min(100, score)),
        confidence=confidence,
        matched_signals=matched + [f"intent:{hit}" for hit in intent_hits],
        excluded_signals=excluded,
    )

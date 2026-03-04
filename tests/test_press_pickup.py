"""Tests for press-pickup/press_pickup.py — pure utility functions."""

from datetime import datetime, timedelta, timezone


# ── _normalize_url ──

class TestNormalizeUrl:
    def test_http_to_https(self, press_pickup_mod):
        assert press_pickup_mod._normalize_url("http://example.com/article") == "https://example.com/article"

    def test_www_stripped(self, press_pickup_mod):
        assert press_pickup_mod._normalize_url("https://www.example.com/article") == "https://example.com/article"

    def test_amp_stripped(self, press_pickup_mod):
        url = "https://example.com/article/amp/"
        assert press_pickup_mod._normalize_url(url) == "https://example.com/article"

    def test_utm_params_stripped(self, press_pickup_mod):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social"
        assert press_pickup_mod._normalize_url(url) == "https://example.com/article"

    def test_fbclid_stripped(self, press_pickup_mod):
        url = "https://example.com/article?fbclid=abc123"
        assert press_pickup_mod._normalize_url(url) == "https://example.com/article"

    def test_trailing_slash_stripped(self, press_pickup_mod):
        assert press_pickup_mod._normalize_url("https://example.com/article/") == "https://example.com/article"

    def test_preserves_meaningful_query(self, press_pickup_mod):
        url = "https://example.com/article?id=42"
        assert "id=42" in press_pickup_mod._normalize_url(url)

    def test_combined_normalization(self, press_pickup_mod):
        url = "http://www.example.com/article?utm_source=fb&fbclid=xyz"
        result = press_pickup_mod._normalize_url(url)
        assert result == "https://example.com/article"


# ── _extract_json_array ──

class TestExtractJsonArray:
    def test_plain_array(self, press_pickup_mod):
        result = press_pickup_mod._extract_json_array('[1, 2, 3]')
        assert result == [1, 2, 3]

    def test_markdown_fenced(self, press_pickup_mod):
        text = '```json\n[{"relevant": true}]\n```'
        result = press_pickup_mod._extract_json_array(text)
        assert result == [{"relevant": True}]

    def test_prose_wrapped(self, press_pickup_mod):
        text = 'Here are the results:\n[{"id": 1}, {"id": 2}]\nThose are the results.'
        result = press_pickup_mod._extract_json_array(text)
        assert len(result) == 2

    def test_nested_objects(self, press_pickup_mod):
        text = '[{"data": [1, 2], "name": "test"}]'
        result = press_pickup_mod._extract_json_array(text)
        assert result[0]["data"] == [1, 2]

    def test_invalid_returns_none(self, press_pickup_mod):
        assert press_pickup_mod._extract_json_array("not json at all") is None

    def test_no_array_returns_none(self, press_pickup_mod):
        assert press_pickup_mod._extract_json_array('{"key": "value"}') is None

    def test_unclosed_bracket(self, press_pickup_mod):
        assert press_pickup_mod._extract_json_array('[1, 2, 3') is None


# ── _extract_social_handle ──

class TestExtractSocialHandle:
    def test_instagram_profile(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://www.instagram.com/rollingstone_mx")
        assert result == ("instagram", "rollingstone_mx")

    def test_instagram_post_returns_none(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://www.instagram.com/p/ABC123")
        assert result is None

    def test_instagram_reel_returns_none(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://www.instagram.com/reel/ABC123")
        assert result is None

    def test_twitter_profile(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://twitter.com/billboard_ar")
        assert result == ("twitter", "billboard_ar")

    def test_twitter_intent_returns_none(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://twitter.com/intent/tweet")
        assert result is None

    def test_x_domain(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://x.com/musicnews")
        assert result == ("twitter", "musicnews")

    def test_facebook_page(self, press_pickup_mod):
        result = press_pickup_mod._extract_social_handle("https://www.facebook.com/rockandpop")
        assert result == ("facebook", "rockandpop")


# ── _normalize_title ──

class TestNormalizeTitle:
    def test_lowercase_strip(self, press_pickup_mod):
        assert press_pickup_mod._normalize_title("  Hello World  ") == "hello world"

    def test_curly_quotes_normalized(self, press_pickup_mod):
        assert press_pickup_mod._normalize_title("\u201cHello\u201d") == '"hello"'

    def test_em_dash_normalized(self, press_pickup_mod):
        assert press_pickup_mod._normalize_title("A \u2014 B") == "a - b"

    def test_guillemets_normalized(self, press_pickup_mod):
        assert press_pickup_mod._normalize_title("\u00abHola\u00bb") == '"hola"'


# ── normalize_country ──

class TestNormalizeCountry:
    def test_accented_to_plain(self, press_pickup_mod):
        assert press_pickup_mod.normalize_country("MÉXICO") == "MEXICO"

    def test_peru_accent(self, press_pickup_mod):
        assert press_pickup_mod.normalize_country("PERÚ") == "PERU"

    def test_passthrough(self, press_pickup_mod):
        assert press_pickup_mod.normalize_country("ARGENTINA") == "ARGENTINA"

    def test_panama(self, press_pickup_mod):
        assert press_pickup_mod.normalize_country("PANAMÁ") == "PANAMA"


# ── parse_search_terms ──

class TestParseSearchTerms:
    def test_comma_separated(self, press_pickup_mod):
        assert press_pickup_mod.parse_search_terms("PNAU, Meduza") == ["PNAU", "Meduza"]

    def test_ft_separator(self, press_pickup_mod):
        result = press_pickup_mod.parse_search_terms("PNAU ft. Meduza")
        assert result == ["PNAU", "Meduza"]

    def test_feat_separator(self, press_pickup_mod):
        result = press_pickup_mod.parse_search_terms("PNAU feat. Meduza")
        assert result == ["PNAU", "Meduza"]

    def test_ampersand_separator(self, press_pickup_mod):
        result = press_pickup_mod.parse_search_terms("PNAU & Meduza")
        assert result == ["PNAU", "Meduza"]

    def test_x_separator(self, press_pickup_mod):
        result = press_pickup_mod.parse_search_terms("PNAU x Meduza")
        assert result == ["PNAU", "Meduza"]

    def test_single_artist(self, press_pickup_mod):
        assert press_pickup_mod.parse_search_terms("Shakira") == ["Shakira"]


# ── Domain helper functions ──

class TestDomainHelpers:
    def test_is_generic_com_true(self, press_pickup_mod):
        assert press_pickup_mod._is_generic_com_domain("rollingstone.com") is True

    def test_is_generic_com_false_for_com_mx(self, press_pickup_mod):
        assert press_pickup_mod._is_generic_com_domain("rollingstone.com.mx") is False

    def test_is_generic_com_false_for_co(self, press_pickup_mod):
        assert press_pickup_mod._is_generic_com_domain("eltiempo.co") is False

    def test_is_generic_com_empty(self, press_pickup_mod):
        assert press_pickup_mod._is_generic_com_domain("") is False

    def test_is_latam_domain_true(self, press_pickup_mod):
        assert press_pickup_mod.is_latam_domain("clarin.com.ar") is True

    def test_is_latam_domain_false(self, press_pickup_mod):
        assert press_pickup_mod.is_latam_domain("nytimes.com") is False

    def test_has_latam_url_indicators_es_path(self, press_pickup_mod):
        assert press_pickup_mod._has_latam_url_indicators("https://site.com/es/article") is True

    def test_has_latam_url_indicators_slug_word(self, press_pickup_mod):
        # Slug words flanked by - or / match
        assert press_pickup_mod._has_latam_url_indicators("https://site.com/espectaculos/article") is True
        assert press_pickup_mod._has_latam_url_indicators("https://site.com/-musica-nueva/article") is True

    def test_has_latam_url_indicators_no_match(self, press_pickup_mod):
        assert press_pickup_mod._has_latam_url_indicators("https://site.com/news/article") is False


# ── _group_entries_by_outlet ──

class TestGroupEntriesByOutlet:
    def _make_entry(self, name, url, title="", in_db=True, url_type="article"):
        return {
            "media_name": name,
            "description": f"Desc for {name}",
            "url": url,
            "title": title,
            "in_database": in_db,
            "url_type": url_type,
        }

    def test_merge_urls_same_outlet(self, press_pickup_mod):
        entries = [
            self._make_entry("Clarín", "https://clarin.com/art1", "Article One"),
            self._make_entry("Clarín", "https://clarin.com/art2", "Article Two"),
        ]
        result = press_pickup_mod._group_entries_by_outlet(entries)
        assert len(result) == 1
        assert len(result[0]["urls"]) == 2

    def test_title_dedup(self, press_pickup_mod):
        entries = [
            self._make_entry("Clarín", "https://clarin.com/art1", "Same Title"),
            self._make_entry("Clarín", "https://clarin.com/art2", "Same Title"),
        ]
        result = press_pickup_mod._group_entries_by_outlet(entries)
        assert len(result[0]["urls"]) == 1

    def test_url_dedup(self, press_pickup_mod):
        entries = [
            self._make_entry("Clarín", "https://clarin.com/art1", "Title A"),
            self._make_entry("Clarín", "https://clarin.com/art1", "Title B"),
        ]
        result = press_pickup_mod._group_entries_by_outlet(entries)
        assert len(result[0]["urls"]) == 1

    def test_in_database_promotion(self, press_pickup_mod):
        entries = [
            self._make_entry("Outlet", "https://outlet.com/art1", "Art", in_db=False),
            self._make_entry("Outlet", "https://outlet.com/art2", "Art2", in_db=True),
        ]
        result = press_pickup_mod._group_entries_by_outlet(entries)
        assert result[0]["in_database"] is True

    def test_multiple_outlets(self, press_pickup_mod):
        entries = [
            self._make_entry("A", "https://a.com/1", "T1"),
            self._make_entry("B", "https://b.com/1", "T2"),
        ]
        result = press_pickup_mod._group_entries_by_outlet(entries)
        assert len(result) == 2


# ── _serper_date_within ──

class TestSerperDateWithin:
    def _cutoff(self, days=7):
        return datetime.now().astimezone() - timedelta(days=days)

    def test_hace_dias_within(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within("hace 3 días", self._cutoff(7)) is True

    def test_hace_dias_outside(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within("hace 30 días", self._cutoff(7)) is False

    def test_hace_semanas_within(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within("hace 1 semana", self._cutoff(14)) is True

    def test_hace_horas_always_recent(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within("hace 5 horas", self._cutoff(1)) is True

    def test_absolute_spanish_date_within(self, press_pickup_mod):
        recent = datetime.now()
        date_str = f"{recent.day} {'ene feb mar abr may jun jul ago sep oct nov dic'.split()[recent.month - 1]} {recent.year}"
        assert press_pickup_mod._serper_date_within(date_str, self._cutoff(7)) is True

    def test_empty_returns_true(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within("", self._cutoff()) is True

    def test_none_returns_true(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within(None, self._cutoff()) is True

    def test_unparseable_returns_true(self, press_pickup_mod):
        assert press_pickup_mod._serper_date_within("some weird string", self._cutoff()) is True

"""Tests for press-pickup/press_pickup.py — pure utility functions."""

import sys
import types
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


# ── _handle_matches_artist_keywords ──

class TestHandleMatchesArtistKeywords:
    def test_exact_normalized_handle_match(self, press_pickup_mod):
        assert press_pickup_mod._handle_matches_artist_keywords("karol_g", ["Karol G"]) is True

    def test_common_suffix_variant_matches(self, press_pickup_mod):
        assert press_pickup_mod._handle_matches_artist_keywords("shakirahq", ["Shakira"]) is True

    def test_short_substring_false_positive_is_rejected(self, press_pickup_mod):
        assert press_pickup_mod._handle_matches_artist_keywords("badgirls", ["Bad"]) is False


# ── _keyword_match_type ──

class TestKeywordMatchType:
    def test_title_match_wins_over_snippet(self, press_pickup_mod):
        patterns = press_pickup_mod._make_keyword_patterns(["Shakira"])
        assert press_pickup_mod._keyword_match_type(patterns, "Shakira portada", "Mention in snippet") == "title"

    def test_snippet_match_is_classified(self, press_pickup_mod):
        patterns = press_pickup_mod._make_keyword_patterns(["Shakira"])
        assert press_pickup_mod._keyword_match_type(patterns, "Festival recap", "Shakira surprised the crowd") == "snippet"

    def test_no_match_returns_none(self, press_pickup_mod):
        patterns = press_pickup_mod._make_keyword_patterns(["Shakira"])
        assert press_pickup_mod._keyword_match_type(patterns, "Festival recap", "No artist mention here") is None


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


# ── _is_ambiguous_artist_query ──

class TestAmbiguousArtistQuery:
    def test_metric_is_treated_as_ambiguous(self, press_pickup_mod):
        assert press_pickup_mod._is_ambiguous_artist_query(["Metric"]) is True

    def test_shakira_is_not_treated_as_ambiguous(self, press_pickup_mod):
        assert press_pickup_mod._is_ambiguous_artist_query(["Shakira"]) is False

    def test_short_artist_is_treated_as_ambiguous(self, press_pickup_mod):
        assert press_pickup_mod._is_ambiguous_artist_query(["LP"]) is True


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

    def test_is_skipped_domain_matches_exact_and_subdomains_only(self, press_pickup_mod):
        assert press_pickup_mod._is_skipped_domain("spotify.com") is True
        assert press_pickup_mod._is_skipped_domain("open.spotify.com") is True
        assert press_pickup_mod._is_skipped_domain("musicaargentina.com.ar") is False

    def test_is_skipped_domain_matches_country_tld_platform_hosts(self, press_pickup_mod):
        assert press_pickup_mod._is_skipped_domain("music.amazon.com.mx") is True
        assert press_pickup_mod._is_skipped_domain("youtube.com.ar") is True
        assert press_pickup_mod._is_skipped_domain("amazonia.com.mx") is False

    def test_is_non_press_url_checks_path_segments(self, press_pickup_mod):
        assert press_pickup_mod._is_non_press_url("https://site.com/category/musica") is True
        assert press_pickup_mod._is_non_press_url("https://site.com/features/searchlight-serenade") is False


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


# ── _build_enriched_queries ──

class TestBuildEnrichedQueries:
    def test_no_release_context_expands_queries_across_regions(self, press_pickup_mod, monkeypatch):
        import shared.database as database

        monkeypatch.setattr(database, "load_release_schedule", lambda _source: [])

        result = press_pickup_mod._build_enriched_queries(["Shakira"])
        google_queries = result["google_news"]
        regions = {}
        for query, gl, hl in google_queries:
            regions.setdefault(gl, []).append((query, hl))

        assert len(google_queries) == 14  # 5 core × 2 + 4 extended × 1
        assert set(regions) == {"MX", "AR", "BR", "CL", "CO", "PE", "EC", "UY", "VE"}
        assert len(regions["MX"]) == 2  # core: 2 shapes
        assert len(regions["BR"]) == 2  # core: 2 shapes
        assert len(regions["PE"]) == 1  # extended: 1 shape
        assert any("música OR musica" in query for query, _hl in regions["MX"])
        assert any(_hl == "pt-BR" for _query, _hl in regions["BR"])

    def test_release_context_builds_three_query_shapes_per_region(self, press_pickup_mod, monkeypatch):
        import shared.database as database

        recent = datetime.now() - timedelta(days=5)
        release = {
            "artist": "Shakira",
            "title": "Las Mujeres Ya No Lloran",
            "format": "Album",
            "date": f"{recent.strftime('%b')} {recent.day}",
        }
        monkeypatch.setattr(database, "load_release_schedule", lambda _source: [release])

        result = press_pickup_mod._build_enriched_queries(["Shakira"])
        google_queries = result["google_news"]
        regions = {}
        for query, gl, hl in google_queries:
            regions.setdefault(gl, []).append((query, hl))

        assert len(google_queries) == 14  # 5 core × 2 + 4 extended × 1
        assert len(regions["MX"]) == 2
        assert len(regions["BR"]) == 2
        assert len(regions["PE"]) == 1
        assert any('"Las Mujeres Ya No Lloran"' in query for query, _hl in regions["MX"])
        assert any("estreno OR lanzamiento OR reseña OR entrevista" in query for query, _hl in regions["MX"])
        assert any("novo álbum" in query for query, _hl in regions["BR"])

    def test_no_release_context_uses_stricter_queries_for_ambiguous_artist(self, press_pickup_mod, monkeypatch):
        import shared.database as database

        monkeypatch.setattr(database, "load_release_schedule", lambda _source: [])

        result = press_pickup_mod._build_enriched_queries(["Metric"])
        google_queries = result["google_news"]
        metric_queries = [query for query, _gl, _hl in google_queries]

        assert len(google_queries) == 14
        assert '"Metric"' not in metric_queries
        assert any("banda OR cantante OR disco" in query for query in metric_queries)
        assert any("estreno OR lanzamiento OR reseña OR entrevista OR concierto" in query for query in metric_queries)


# ── Outlet adapters ──

class TestOutletAdapters:
    def test_get_outlet_adapter_specs_returns_expected_first_batch(self, press_pickup_mod):
        specs = press_pickup_mod._get_outlet_adapter_specs()
        adapter_ids = {spec.adapter_id for spec in specs}

        assert adapter_ids == {
            "billboard-br",
            "popline",
            "rolling-stone-mx",
            "elpais-uy",
            "rpp",
            "biobio",
            "expreso",
        }
        assert "billboard-ar" not in adapter_ids
        assert "indie-hoy" not in adapter_ids
        assert "oglobo" not in adapter_ids

    def test_scan_outlet_adapters_returns_preclassified_wordpress_hits(self, press_pickup_mod, monkeypatch):
        class FakeResponse:
            status_code = 200

            def json(self):
                return [{
                    "title": {"rendered": "<h1>Festival recap</h1>"},
                    "excerpt": {"rendered": "<p>Shakira surprised the audience.</p>"},
                    "link": "https://example.com/article-1",
                }]

        class FakeSession:
            def get(self, url, params=None, timeout=None):
                assert url == "https://example.com/wp-json/wp/v2/posts"
                assert params["search"] == "Shakira"
                return FakeResponse()

            def close(self):
                return None

        spec = press_pickup_mod.OutletAdapterSpec(
            adapter_id="test-wp",
            pattern_type="wordpress",
            outlet_name="Test Outlet",
            country="MEXICO",
            description="Test description",
            domain="example.com",
            website="https://example.com",
            wp_api_url="https://example.com/wp-json/wp/v2/posts",
        )

        monkeypatch.setattr(press_pickup_mod, "_build_adapter_session", lambda: FakeSession())

        results = press_pickup_mod.scan_outlet_adapters(
            ["Shakira"],
            cutoff=datetime.now().astimezone() - timedelta(days=7),
            adapter_specs=(spec,),
        )

        assert len(results) == 1
        assert results[0]["feed_media_name"] == "Test Outlet"
        assert results[0]["_source"] == "adapter"
        assert results[0]["_keyword_match"] == "snippet"
        assert results[0]["snippet"] == "Shakira surprised the audience."

    def test_scan_outlet_adapters_returns_preclassified_html_hits(self, press_pickup_mod, monkeypatch):
        class FakeResponse:
            status_code = 200
            text = """
            <html>
              <body>
                <a href="/musica/shakira-portada">Shakira portada exclusiva en Lima</a>
                <a href="/musica/otra-nota">Otra nota sin match</a>
              </body>
            </html>
            """

        class FakeSession:
            def get(self, url, params=None, timeout=None):
                assert url == "https://example.com/buscar?q=Shakira"
                return FakeResponse()

            def close(self):
                return None

        spec = press_pickup_mod.OutletAdapterSpec(
            adapter_id="test-html",
            pattern_type="html",
            outlet_name="HTML Outlet",
            country="PERU",
            description="HTML outlet description",
            domain="example.com",
            website="https://example.com",
            search_url_template="https://example.com/buscar?q={query}",
        )

        monkeypatch.setattr(press_pickup_mod, "_build_adapter_session", lambda: FakeSession())

        results = press_pickup_mod.scan_outlet_adapters(
            ["Shakira"],
            cutoff=datetime.now().astimezone() - timedelta(days=7),
            adapter_specs=(spec,),
        )

        assert len(results) == 1
        assert results[0]["link"] == "https://example.com/musica/shakira-portada"
        assert results[0]["feed_country"] == "PERU"
        assert results[0]["_keyword_match"] == "title"

    def test_run_press_pickup_keeps_adapter_snippet_match_for_known_outlet(
        self, press_pickup_mod, fixture_press_csv, monkeypatch
    ):
        original_exists = press_pickup_mod.os.path.exists

        def fake_exists(path):
            path_str = str(path)
            if path_str.endswith("social_handle_registry.json"):
                return False
            if path_str.endswith("feed_registry.json"):
                return False
            return original_exists(path)

        monkeypatch.setattr(press_pickup_mod.os.path, "exists", fake_exists)
        monkeypatch.setattr(press_pickup_mod, "scan_outlet_feeds", lambda *args, **kwargs: [])
        monkeypatch.setattr(press_pickup_mod, "mine_outlet_sitemaps", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            press_pickup_mod,
            "scan_outlet_adapters",
            lambda *args, **kwargs: [{
                "title": "Festival recap",
                "link": "https://www.rollingstone.com.mx/musica/festival-recap",
                "snippet": "Shakira delivered the headline performance of the night.",
                "domain": "rollingstone.com.mx",
                "source": "Rolling Stone México",
                "feed_country": "MÉXICO",
                "feed_description": "Music magazine",
                "feed_media_name": "Rolling Stone México",
                "_keyword_match": "snippet",
                "_source": "adapter",
            }],
        )
        monkeypatch.setattr(
            press_pickup_mod,
            "_build_enriched_queries",
            lambda _keywords: {
                "google_news": [],
                "brave_news": [],
                "brave_web": [],
                "tavily_news": "",
                "tavily_web": "",
                "ddg": [],
                "releases": [],
            },
        )
        monkeypatch.setattr(press_pickup_mod, "_groq_filter_relevance", lambda results, *args, **kwargs: results)
        monkeypatch.setattr(press_pickup_mod, "_groq_enrich_descriptions", lambda *args, **kwargs: {})

        result = press_pickup_mod.run_press_pickup(
            "Shakira",
            days=7,
            press_db_path=str(fixture_press_csv),
        )

        assert "MEXICO" in result
        assert result["MEXICO"][0]["media_name"] == "Rolling Stone México"
        assert result["MEXICO"][0]["urls"][0]["title"] == "Festival recap"


# ── Source-name fallback ──

class TestSourceNameMatching:
    def test_matches_unique_prefix_against_press_db(self, press_pickup_mod, press_index):
        entry = press_pickup_mod._match_source_name_to_media("Rolling Stone", press_index)
        assert entry["name"] == "Rolling Stone México"

    def test_google_news_rss_preserves_source_name_when_decode_fails(self, press_pickup_mod, monkeypatch):
        import requests

        google_link = "https://news.google.com/articles/CBMiS2h0dHBzOi8vbmV3cy5nb29nbGUuY29tL2FydGljbGVzL2FiYzEyM9IBAA"
        xml = f"""
        <rss>
          <channel>
            <item>
              <title>Shakira portada - Rolling Stone México</title>
              <link>{google_link}</link>
              <source>Rolling Stone México</source>
              <description>Shakira aparece en portada.</description>
              <pubDate>Sat, 07 Mar 2026 12:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
        """.strip().encode("utf-8")

        class FakeGetResponse:
            content = xml

            def raise_for_status(self):
                return None

        class FakeHeadResponse:
            def __init__(self, url):
                self.url = url

        monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeGetResponse())
        monkeypatch.setattr(requests, "head", lambda *args, **kwargs: FakeHeadResponse(google_link))
        monkeypatch.setitem(
            sys.modules,
            "googlenewsdecoder",
            types.SimpleNamespace(new_decoderv1=lambda _url: {"status": False}),
        )

        cutoff = datetime.now().astimezone() - timedelta(days=7)
        results = press_pickup_mod.google_news_rss("Shakira", days=7, cutoff=cutoff)

        assert len(results) == 1
        assert results[0]["link"] == google_link
        assert results[0]["_source_name_match"] == "Rolling Stone México"

    def test_run_press_pickup_uses_source_name_fallback_for_google_news_links(
        self, press_pickup_mod, fixture_press_csv, monkeypatch
    ):
        original_exists = press_pickup_mod.os.path.exists

        def fake_exists(path):
            path_str = str(path)
            if path_str.endswith("social_handle_registry.json"):
                return False
            if path_str.endswith("feed_registry.json"):
                return False
            return original_exists(path)

        monkeypatch.setattr(press_pickup_mod.os.path, "exists", fake_exists)
        monkeypatch.setattr(press_pickup_mod, "scan_outlet_feeds", lambda *args, **kwargs: [])
        monkeypatch.setattr(press_pickup_mod, "mine_outlet_sitemaps", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            press_pickup_mod,
            "_build_enriched_queries",
            lambda _keywords: {
                "google_news": [('"Shakira"', "MX", "es-419")],
                "brave_news": [],
                "brave_web": [],
                "tavily_news": "",
                "tavily_web": "",
                "ddg": [],
                "releases": [],
            },
        )
        monkeypatch.setattr(
            press_pickup_mod,
            "google_news_rss",
            lambda *args, **kwargs: [{
                "title": "Shakira portada",
                "link": "https://news.google.com/articles/abc123",
                "snippet": "Shakira aparece en portada.",
                "domain": "news.google.com",
                "source": "Rolling Stone México",
                "_source_name_match": "Rolling Stone México",
            }],
        )
        monkeypatch.setattr(press_pickup_mod, "_groq_filter_relevance", lambda results, *args, **kwargs: results)
        monkeypatch.setattr(press_pickup_mod, "_groq_enrich_descriptions", lambda *args, **kwargs: {})

        result = press_pickup_mod.run_press_pickup(
            "Shakira",
            days=7,
            press_db_path=str(fixture_press_csv),
        )

        assert "MEXICO" in result
        assert result["MEXICO"][0]["media_name"] == "Rolling Stone México"

    def test_run_press_pickup_keeps_feed_snippet_match_for_known_outlet(
        self, press_pickup_mod, fixture_press_csv, monkeypatch
    ):
        original_exists = press_pickup_mod.os.path.exists

        def fake_exists(path):
            path_str = str(path)
            if path_str.endswith("social_handle_registry.json"):
                return False
            if path_str.endswith("feed_registry.json"):
                return False
            return original_exists(path)

        monkeypatch.setattr(press_pickup_mod.os.path, "exists", fake_exists)
        monkeypatch.setattr(
            press_pickup_mod,
            "scan_outlet_feeds",
            lambda *args, **kwargs: [{
                "title": "Festival recap",
                "link": "https://www.rollingstone.com.mx/musica/festival-recap",
                "snippet": "Shakira delivered the headline performance of the night.",
                "domain": "rollingstone.com.mx",
                "source": "Rolling Stone México",
                "feed_country": "MÉXICO",
                "feed_description": "Music magazine",
                "feed_media_name": "Rolling Stone México",
                "_keyword_match": "snippet",
            }],
        )
        monkeypatch.setattr(press_pickup_mod, "mine_outlet_sitemaps", lambda *args, **kwargs: [])
        monkeypatch.setattr(
            press_pickup_mod,
            "_build_enriched_queries",
            lambda _keywords: {
                "google_news": [],
                "brave_news": [],
                "brave_web": [],
                "tavily_news": "",
                "tavily_web": "",
                "ddg": [],
                "releases": [],
            },
        )
        monkeypatch.setattr(press_pickup_mod, "_groq_filter_relevance", lambda results, *args, **kwargs: results)
        monkeypatch.setattr(press_pickup_mod, "_groq_enrich_descriptions", lambda *args, **kwargs: {})

        result = press_pickup_mod.run_press_pickup(
            "Shakira",
            days=7,
            press_db_path=str(fixture_press_csv),
        )

        assert "MEXICO" in result
        assert result["MEXICO"][0]["media_name"] == "Rolling Stone México"
        assert result["MEXICO"][0]["urls"][0]["title"] == "Festival recap"


# ── _groq_filter_relevance ──

class TestGroqFilterRelevance:
    def test_no_api_key_keeps_snippet_only_results_unreviewed(self, press_pickup_mod, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        results = [{
            "title": "Festival recap",
            "link": "https://example.com/article",
            "snippet": "Shakira performed a surprise set.",
            "domain": "example.com",
        }]

        kept = press_pickup_mod._groq_filter_relevance(
            results,
            "Shakira",
            ["Shakira"],
            releases=[],
            log_fn=lambda _msg: None,
        )

        assert len(kept) == 1
        assert kept[0]["_groq_unreviewed"] is True

    def test_clusters_duplicate_snippet_only_titles_before_review(self, press_pickup_mod, monkeypatch):
        import requests

        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        prompts = []

        class FakeResponse:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "[true]"}}]}

        def fake_post(*args, **kwargs):
            prompts.append(kwargs["json"]["messages"][0]["content"])
            return FakeResponse()

        monkeypatch.setattr(requests, "post", fake_post)
        results = [
            {
                "title": "Festival recap",
                "link": "https://example.com/article-1",
                "snippet": "Shakira surprised the audience.",
                "domain": "example.com",
            },
            {
                "title": "Festival recap",
                "link": "https://another.com/article-2",
                "snippet": "Shakira closed the show.",
                "domain": "another.com",
            },
        ]

        kept = press_pickup_mod._groq_filter_relevance(
            results,
            "Shakira",
            ["Shakira"],
            releases=[],
            log_fn=lambda _msg: None,
        )

        assert len(prompts) == 1
        assert prompts[0].count('Title: "Festival recap"') == 1
        assert len(kept) == 2
        assert kept[0]["_story_cluster_size"] == 2

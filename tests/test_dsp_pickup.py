"""Tests for dsp-pickup/dsp_pickup.py — normalize_name and check_release_in_playlist."""


# ── normalize_name ──

class TestNormalizeName:
    def test_strips_parenthetical(self, dsp_pickup_mod):
        assert dsp_pickup_mod.normalize_name("Song (Remix)") == "song"

    def test_strips_feat(self, dsp_pickup_mod):
        result = dsp_pickup_mod.normalize_name("Song feat. Artist")
        assert result == "song"

    def test_strips_ft(self, dsp_pickup_mod):
        result = dsp_pickup_mod.normalize_name("Song ft. Artist")
        assert result == "song"

    def test_strips_brackets(self, dsp_pickup_mod):
        assert dsp_pickup_mod.normalize_name("Song [Deluxe]") == "song"

    def test_strips_dash_suffix(self, dsp_pickup_mod):
        assert dsp_pickup_mod.normalize_name("Song - Live") == "song"

    def test_accents_normalized(self, dsp_pickup_mod):
        assert dsp_pickup_mod.normalize_name("María") == "maria"

    def test_plain_text(self, dsp_pickup_mod):
        assert dsp_pickup_mod.normalize_name("simple song") == "simple song"


# ── check_release_in_playlist ──

class TestCheckReleaseInPlaylist:
    def _release(self, artist="Test Artist", title="Test Song", focus_track=""):
        return {"artist": artist, "title": title, "focus_track": focus_track}

    def _track(self, artist="Test Artist", track="Test Song", album="Test Album", position=1):
        return {
            "artist": artist,
            "artists_list": [artist],
            "track": track,
            "album": album,
            "position": position,
            "added_at": "",
            "artwork_url": "",
            "spotify_uri": "",
        }

    def test_exact_match(self, dsp_pickup_mod):
        release = self._release("Bad Bunny", "Monaco")
        tracks = [self._track("Bad Bunny", "Monaco")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is not None
        assert result["playlist_track"] == "Monaco"

    def test_partial_artist_match(self, dsp_pickup_mod):
        release = self._release("Bad Bunny", "Monaco")
        tracks = [self._track("Bad Bunny & Friends", "Monaco")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is not None

    def test_title_substring_long(self, dsp_pickup_mod):
        release = self._release("Artist", "Beautiful Song")
        tracks = [self._track("Artist", "Beautiful Song (Remix)")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is not None

    def test_focus_track_match(self, dsp_pickup_mod):
        release = self._release("Artist", "Album Name", focus_track="Focus Track")
        tracks = [self._track("Artist", "Focus Track", album="Album Name")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is not None

    def test_album_match(self, dsp_pickup_mod):
        release = self._release("Artist", "Album Name")
        tracks = [self._track("Artist", "Some Other Track", album="Album Name")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is not None

    def test_placeholder_focus_track_ignored(self, dsp_pickup_mod):
        """Focus tracks like '-', 'N/A', 'TBD' should be treated as empty."""
        release = self._release("Artist", "Album Name", focus_track="-")
        tracks = [self._track("Different Artist", "-")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is None

    def test_no_match_returns_none(self, dsp_pickup_mod):
        release = self._release("Artist A", "Song A")
        tracks = [self._track("Artist B", "Song B")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        assert result is None

    def test_short_title_no_substring(self, dsp_pickup_mod):
        """Short titles (<4 chars) should not match via substring."""
        release = self._release("Artist", "Abc")
        tracks = [self._track("Artist", "Abcdef")]
        result = dsp_pickup_mod.check_release_in_playlist(release, tracks)
        # "abc" is 3 chars — substring match requires >=4
        assert result is None

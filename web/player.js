/* Letterboxd Cinema player — plays a Jellyfin item inside the page.
   Jellyfin decides direct-play vs transcode and serves HLS; hls.js feeds the <video>. */

const Player = (() => {
  const TICK = 10000000; // Jellyfin ticks per second
  let el, video, hls, film, src, playSessionId, playMethod, progressTimer, hideTimer, subIndex = -1, audioIndex = null, ctx;

  const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
  const canHevc = MediaSource.isTypeSupported('video/mp4; codecs="hvc1.1.6.L120.90"');

  function deviceProfile() {
    return {
      MaxStreamingBitrate: 120000000, MaxStaticBitrate: 120000000, MusicStreamingTranscodingBitrate: 384000,
      DirectPlayProfiles: [
        { Container: 'mp4,m4v', Type: 'Video', VideoCodec: 'h264,vp9,av1' + (canHevc ? ',hevc' : ''), AudioCodec: 'aac,mp3,opus,flac' },
        { Container: 'webm', Type: 'Video', VideoCodec: 'vp8,vp9,av1', AudioCodec: 'opus,vorbis' },
      ],
      TranscodingProfiles: [
        { Container: 'ts', Type: 'Video', VideoCodec: 'h264', AudioCodec: 'aac', Context: 'Streaming', Protocol: 'hls', MaxAudioChannels: '2', MinSegments: 1, BreakOnNonKeyFrames: true },
      ],
      SubtitleProfiles: [
        { Format: 'vtt', Method: 'External' }, { Format: 'subrip', Method: 'External' }, { Format: 'ass', Method: 'External' }, { Format: 'ssa', Method: 'External' },
      ],
      CodecProfiles: [
        { Type: 'Video', Codec: 'h264', Conditions: [{ Condition: 'LessThanEqual', Property: 'VideoLevel', Value: '52', IsRequired: false }] },
      ],
    };
  }

  async function playbackInfo(startTicks) {
    const body = { DeviceProfile: deviceProfile(), UserId: ctx.session.userId, StartTimeTicks: startTicks, AutoOpenLiveStream: true,
      EnableDirectPlay: true, EnableDirectStream: true, EnableTranscoding: true, MaxStreamingBitrate: 120000000 };
    if (subIndex >= 0) body.SubtitleStreamIndex = subIndex;
    if (audioIndex != null) body.AudioStreamIndex = audioIndex;
    return ctx.api(`/Items/${film.id}/PlaybackInfo`, { method: 'POST', body });
  }

  function buildUI() {
    el = document.createElement('div'); el.className = 'player'; el.id = 'player';
    el.innerHTML = `
      <video playsinline crossorigin="anonymous"></video>
      <div class="p-scrim"></div>
      <div class="p-top"><div class="p-title"><span class="label p-eyebrow"></span><span class="p-name"></span></div><button class="p-close" title="Close (Esc)">Close <span aria-hidden="true">✕</span></button></div>
      <div class="p-spinner" hidden></div>
      <div class="p-bottom">
        <div class="p-bar"><div class="p-buffer"></div><div class="p-played"></div><input class="p-seek" type="range" min="0" max="1000" value="0" step="1" aria-label="Seek"></div>
        <div class="p-ctl">
          <div class="p-left">
            <button class="p-play" title="Play/pause (Space)"></button>
            <span class="p-time"><span class="p-cur">0:00</span> <span class="p-sep">/</span> <span class="p-dur">0:00</span></span>
          </div>
          <div class="p-right">
            <div class="p-menu-wrap"><button class="p-audio" title="Audio">Audio</button><div class="p-menu" data-menu="audio" hidden></div></div>
            <div class="p-menu-wrap"><button class="p-subs" title="Subtitles">Subtitles</button><div class="p-menu" data-menu="subs" hidden></div></div>
            <button class="p-mute" title="Mute (M)">Sound</button>
            <button class="p-full" title="Fullscreen (F)">Fullscreen</button>
          </div>
        </div>
      </div>
      <div class="p-error" hidden></div>`;
    document.body.appendChild(el);
    video = el.querySelector('video');
    const q = (s) => el.querySelector(s);
    q('.p-close').onclick = close;
    q('.p-play').onclick = toggle;
    q('.p-mute').onclick = () => { video.muted = !video.muted; q('.p-mute').textContent = video.muted ? 'Muted' : 'Sound'; };
    q('.p-full').onclick = () => document.fullscreenElement ? document.exitFullscreen() : el.requestFullscreen?.();
    q('.p-audio').onclick = () => toggleMenu('audio');
    q('.p-subs').onclick = () => toggleMenu('subs');
    q('.p-seek').addEventListener('input', (e) => { const d = duration(); if (d) seek(e.target.value / 1000 * d); });
    video.addEventListener('click', toggle);
    video.addEventListener('dblclick', () => q('.p-full').click());
    video.addEventListener('timeupdate', tick);
    video.addEventListener('progress', tick);
    video.addEventListener('play', () => { q('.p-play').classList.add('is-playing'); wake(); });
    video.addEventListener('pause', () => { q('.p-play').classList.remove('is-playing'); wake(true); report('Progress'); });
    video.addEventListener('waiting', () => spin(true));
    video.addEventListener('playing', () => { spin(false); el.classList.add('is-live'); });
    video.addEventListener('canplay', () => spin(false));
    video.addEventListener('timeupdate', () => { if (!video.paused && video.readyState >= 3) spin(false); });
    video.addEventListener('ended', close);
    el.addEventListener('mousemove', () => wake());
    el.addEventListener('click', (e) => { if (!e.target.closest('.p-menu-wrap')) el.querySelectorAll('.p-menu').forEach(m => m.hidden = true); });
  }

  // Jellyfin's HLS playlist spans the whole film, so the timeline is absolute for both direct play and transcodes.
  const duration = () => (isFinite(video.duration) && video.duration) || (film.r ? film.r * 60 : 0);
  const position = () => video.currentTime || 0;

  function tick() {
    const d = duration(); if (!d) return;
    const q = (s) => el.querySelector(s);
    q('.p-cur').textContent = fmt(position()); q('.p-dur').textContent = fmt(d);
    q('.p-played').style.width = (position() / d * 100) + '%';
    if (!q('.p-seek').matches(':active')) q('.p-seek').value = Math.round(position() / d * 1000);
    try { const b = video.buffered; if (b.length) q('.p-buffer').style.width = (b.end(b.length - 1) / d * 100) + '%'; } catch {}
  }

  let spinTimer;
  function spin(on) {
    clearTimeout(spinTimer);
    if (on) spinTimer = setTimeout(() => { el.querySelector('.p-spinner').hidden = false; }, 1200);
    else el.querySelector('.p-spinner').hidden = true;
  }

  function wake(stay) {
    el.classList.remove('idle'); clearTimeout(hideTimer);
    if (!stay && !video.paused) hideTimer = setTimeout(() => el.classList.add('idle'), 2800);
  }
  function toggle() { video.paused ? video.play() : video.pause(); }

  async function load(startSeconds) {
    const q = (s) => el.querySelector(s); spin(true); q('.p-error').hidden = true;
    if (hls) { hls.destroy(); hls = null; }
    const info = await playbackInfo(Math.round(startSeconds * TICK));
    if (info.ErrorCode) throw new Error(info.ErrorCode);
    src = info.MediaSources[0]; playSessionId = info.PlaySessionId;
    if (src.SupportsDirectPlay || src.SupportsDirectStream) {
      playMethod = src.SupportsDirectPlay ? 'DirectPlay' : 'DirectStream';
      video.src = `/Videos/${film.id}/stream.${src.Container}?static=true&mediaSourceId=${src.Id}&api_key=${ctx.session.token}&playSessionId=${playSessionId}`;
      video.currentTime = startSeconds;
    } else if (src.TranscodingUrl) {
      playMethod = 'Transcode';
      const url = src.TranscodingUrl.startsWith('/') ? src.TranscodingUrl : '/' + src.TranscodingUrl;
      if (Hls.isSupported()) {
        hls = new Hls({ maxBufferLength: 60, startPosition: startSeconds || -1 });
        hls.loadSource(url); hls.attachMedia(video);
        hls.on(Hls.Events.ERROR, (_, d) => { if (d.fatal) fail('Playback failed (' + d.type + ')'); });
      } else { video.src = url; video.currentTime = startSeconds; } // Safari plays HLS natively
    } else throw new Error('No playable source');
    buildTracks();
    await video.play().catch(() => {});
    report('Playing');
    clearInterval(progressTimer); progressTimer = setInterval(() => report('Progress'), 10000);
  }

  function seek(seconds) { video.currentTime = seconds; report('Progress'); }

  function buildTracks() {
    const q = (s) => el.querySelector(s);
    const streams = src.MediaStreams || [];
    const subs = streams.filter(s => s.Type === 'Subtitle' && s.IsTextSubtitleStream);
    const audios = streams.filter(s => s.Type === 'Audio');
    // subtitles: external text tracks straight from Jellyfin
    [...video.querySelectorAll('track')].forEach(t => t.remove());
    subs.forEach(s => {
      const t = document.createElement('track'); t.kind = 'subtitles'; t.label = s.DisplayTitle || s.Language || 'Subtitles'; t.srclang = s.Language || '';
      t.src = `/Videos/${film.id}/${src.Id}/Subtitles/${s.Index}/0/Stream.vtt?api_key=${ctx.session.token}`; t.dataset.index = s.Index; video.appendChild(t);
    });
    const subMenu = q('[data-menu="subs"]');
    subMenu.innerHTML = [`<button data-sub="-1" ${subIndex < 0 ? 'aria-pressed="true"' : ''}>Off</button>`]
      .concat(subs.map(s => `<button data-sub="${s.Index}" ${subIndex === s.Index ? 'aria-pressed="true"' : ''}>${s.DisplayTitle || s.Language}</button>`)).join('');
    subMenu.onclick = (e) => { const b = e.target.closest('[data-sub]'); if (!b) return; setSub(+b.dataset.sub); subMenu.hidden = true; };
    q('.p-subs').hidden = subs.length === 0;
    applySub();
    const audMenu = q('[data-menu="audio"]');
    audMenu.innerHTML = audios.map(a => `<button data-aud="${a.Index}" ${(audioIndex ?? src.DefaultAudioStreamIndex) === a.Index ? 'aria-pressed="true"' : ''}>${a.DisplayTitle || a.Language || 'Audio'}</button>`).join('');
    audMenu.onclick = (e) => { const b = e.target.closest('[data-aud]'); if (!b) return; audioIndex = +b.dataset.aud; audMenu.hidden = true; const p = position(); load(p).catch(x => fail(x.message)); };
    q('.p-audio').hidden = audios.length < 2;
  }
  function setSub(i) { subIndex = i; applySub(); el.querySelectorAll('[data-sub]').forEach(b => b.setAttribute('aria-pressed', +b.dataset.sub === i)); }
  function applySub() { [...video.textTracks].forEach(t => { const idx = +[...video.querySelectorAll('track')].find(x => x.track === t)?.dataset.index; t.mode = idx === subIndex ? 'showing' : 'hidden'; }); }
  function toggleMenu(name) { el.querySelectorAll('.p-menu').forEach(m => { if (m.dataset.menu === name) m.hidden = !m.hidden; else m.hidden = true; }); }

  function report(kind) {
    if (!src) return;
    const body = { ItemId: film.id, MediaSourceId: src.Id, PlaySessionId: playSessionId, PositionTicks: Math.round(position() * TICK), IsPaused: video.paused, IsMuted: video.muted,
      CanSeek: true, PlayMethod: playMethod, AudioStreamIndex: audioIndex ?? src.DefaultAudioStreamIndex, SubtitleStreamIndex: subIndex, VolumeLevel: Math.round(video.volume * 100), EventName: kind === 'Progress' ? 'timeupdate' : undefined };
    const path = kind === 'Playing' ? '/Sessions/Playing' : kind === 'Stopped' ? '/Sessions/Playing/Stopped' : '/Sessions/Playing/Progress';
    ctx.api(path, { method: 'POST', body }).catch(() => {});
  }

  function fail(msg) { const e = el.querySelector('.p-error'); e.textContent = msg; e.hidden = false; spin(false); el.classList.add('is-live'); }

  function onKey(e) {
    if (!el || el.hidden) return;
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
    const k = e.key.toLowerCase();
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === ' ' || k === 'k') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); seek(Math.min(duration(), position() + 10)); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); seek(Math.max(0, position() - 10)); }
    else if (k === 'f') el.querySelector('.p-full').click();
    else if (k === 'm') el.querySelector('.p-mute').click();
    e.stopPropagation();
  }

  async function open(f, context) {
    ctx = context; film = f; subIndex = -1; audioIndex = null;
    if (!el) buildUI();
    el.classList.remove('is-live'); el.hidden = false; document.body.style.overflow = 'hidden';
    el.querySelector('.p-name').textContent = f.t; el.querySelector('.p-eyebrow').textContent = [f.d, f.y].filter(Boolean).join(' · ');
    document.addEventListener('keydown', onKey, true);
    const start = f.pos && f.pos > 60 * TICK ? f.pos / TICK : 0;
    try { await load(start); } catch (e) { fail('Could not start playback — ' + e.message); }
    wake();
  }
  function close() {
    if (!el || el.hidden) return;
    clearInterval(progressTimer); report('Stopped');
    film.pos = Math.round(position() * TICK); ctx.onStop?.(film);
    if (hls) { hls.destroy(); hls = null; }
    video.pause(); video.removeAttribute('src'); video.load();
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    el.hidden = true; document.body.style.overflow = '';
    document.removeEventListener('keydown', onKey, true);
  }

  return { open, close };
})();

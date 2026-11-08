/* STAND — visore 3D in WebGL2, senza librerie.
 * Vista ortografica come un disegno tecnico: facce grafite, spigoli chiari, strumento a contorno,
 * piano millimetrato sotto. Trascina = ruota, tasto destro / Maiusc + trascina = sposta,
 * rotella / pizzico = zoom, doppio clic = vista iniziale. Asse Z in alto, millimetri.
 */
(function () {
  "use strict";

  const COLORS = {
    face: { base: [0.075, 0.088, 0.106], bar: [0.075, 0.088, 0.106], deck: [0.11, 0.13, 0.157], prop: [0.11, 0.13, 0.157] },
    line: { base: [0.66, 0.70, 0.76, 1], bar: [0.66, 0.70, 0.76, 1], deck: [0.91, 0.925, 0.945, 1], prop: [0.91, 0.925, 0.945, 1] },
    device: [0.49, 0.53, 0.58, 0.85],
    gridMinor: [0.11, 0.125, 0.145, 1],
    gridMajor: [0.16, 0.18, 0.21, 1],
    axis: [1.0, 0.416, 0.169, 0.55],
  };
  const HOME = { yaw: 225, pitch: 24 };

  // ---------------------------------------------------------------- matrici (colonna per colonna)
  function mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++)
      for (let r = 0; r < 4; r++)
        o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    return o;
  }
  function ortho(l, r, b, t, n, f) {
    return new Float32Array([2 / (r - l), 0, 0, 0, 0, 2 / (t - b), 0, 0, 0, 0, -2 / (f - n), 0,
      -(r + l) / (r - l), -(t + b) / (t - b), -(f + n) / (f - n), 1]);
  }
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const norm = (a) => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
  function lookAt(eye, at, up) {
    const z = norm(sub(eye, at)), x = norm(cross(up, z)), y = cross(z, x);
    return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0,
      -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
  }

  // ---------------------------------------------------------------- shader
  const VS_FACE = `#version 300 es
  in vec3 aPos; in vec3 aCol; uniform mat4 uMVP; out vec3 vPos; out vec3 vCol;
  void main(){ vPos = aPos; vCol = aCol; gl_Position = uMVP * vec4(aPos, 1.0); }`;
  const FS_FACE = `#version 300 es
  precision highp float; in vec3 vPos; in vec3 vCol; uniform vec3 uLight; out vec4 o;
  void main(){
    vec3 n = normalize(cross(dFdx(vPos), dFdy(vPos)));
    float l = abs(dot(n, uLight));
    o = vec4(vCol * (0.75 + 0.55 * l), 1.0);
  }`;
  const VS_LINE = `#version 300 es
  in vec3 aPos; in vec4 aCol; uniform mat4 uMVP; out vec4 vCol;
  void main(){ vCol = aCol; gl_Position = uMVP * vec4(aPos, 1.0); }`;
  const FS_LINE = `#version 300 es
  precision mediump float; in vec4 vCol; out vec4 o; void main(){ o = vCol; }`;

  function program(gl, vs, fs) {
    const p = gl.createProgram();
    for (const [type, src] of [[gl.VERTEX_SHADER, vs], [gl.FRAGMENT_SHADER, fs]]) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      gl.attachShader(p, s);
    }
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
    return p;
  }

  class StandViewer {
    constructor(canvas) {
      this.canvas = canvas;
      const gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: false });
      if (!gl) throw new Error("WebGL2 non disponibile");
      this.gl = gl;
      this.pFace = program(gl, VS_FACE, FS_FACE);
      this.pLine = program(gl, VS_LINE, FS_LINE);
      this.face = null; this.lines = null; this.ghost = null; this.grid = null;
      this.cam = { yaw: HOME.yaw, pitch: HOME.pitch, zoom: 1, pan: [0, 0] };
      this.center = [0, 0, 0]; this.radius = 300;
      this._dirty = true;
      this._bind();
      new ResizeObserver(() => this.draw()).observe(canvas);
      this._loop = this._loop.bind(this);
      requestAnimationFrame(this._loop);
    }

    // ------------------------------------------------------------ dati
    _buffer(data, layout) {
      const gl = this.gl, vao = gl.createVertexArray(), buf = gl.createBuffer();
      gl.bindVertexArray(vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      const stride = layout.reduce((s, l) => s + l.n, 0) * 4;
      let off = 0;
      for (const l of layout) {
        const loc = gl.getAttribLocation(l.prog, l.name);
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, l.n, gl.FLOAT, false, stride, off);
        off += l.n * 4;
      }
      gl.bindVertexArray(null);
      return { vao, buf, count: data.length / (stride / 4) };
    }

    _free(o) { if (o) { this.gl.deleteBuffer(o.buf); this.gl.deleteVertexArray(o.vao); } }

    setMesh(data, keepCamera) {
      const tri = [], lin = [], gh = [];
      for (const p of data.parts) {
        const P = p.pos, fc = COLORS.face[p.kind] || COLORS.face.deck, lc = COLORS.line[p.kind] || COLORS.line.deck;
        for (const i of p.idx) tri.push(P[i * 3], P[i * 3 + 1], P[i * 3 + 2], fc[0], fc[1], fc[2]);
        for (const i of p.edges) lin.push(P[i * 3], P[i * 3 + 1], P[i * 3 + 2], lc[0], lc[1], lc[2], lc[3]);
      }
      const D = data.device.pos;
      for (const i of data.device.edges) gh.push(D[i * 3], D[i * 3 + 1], D[i * 3 + 2], ...COLORS.device);
      [this.face, this.lines, this.ghost].forEach((o) => this._free(o));
      const L = (prog) => [{ prog, name: "aPos", n: 3 }, { prog, name: "aCol", n: 4 }];
      this.face = this._buffer(new Float32Array(tri), [{ prog: this.pFace, name: "aPos", n: 3 }, { prog: this.pFace, name: "aCol", n: 3 }]);
      this.lines = this._buffer(new Float32Array(lin), L(this.pLine));
      this.ghost = this._buffer(new Float32Array(gh), L(this.pLine));

      const [lo, hi] = data.bounds;
      const firstTime = !this._bounds;
      this._bounds = [lo, hi];
      if (!keepCamera || firstTime) {
        this.center = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
        this.radius = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2;
        this._makeGrid(lo, hi);
        if (!keepCamera) this.reset(false);
      }
      this.draw();
    }

    _makeGrid(lo, hi) {
      const m = 60, step = 10;
      const x0 = Math.floor((lo[0] - m) / step) * step, x1 = Math.ceil((hi[0] + m) / step) * step;
      const y0 = Math.floor((lo[1] - m) / step) * step, y1 = Math.ceil((hi[1] + m) / step) * step;
      const v = [], z = -0.05;
      const push = (a, b, c) => v.push(a[0], a[1], z, ...c, b[0], b[1], z, ...c);
      for (let x = x0; x <= x1; x += step) push([x, y0], [x, y1], x % 100 === 0 ? COLORS.gridMajor : COLORS.gridMinor);
      for (let y = y0; y <= y1; y += step) push([x0, y], [x1, y], y % 100 === 0 ? COLORS.gridMajor : COLORS.gridMinor);
      // asse X del supporto (fronte -> retro) in arancio tenue, sulla mezzeria
      push([x0, 0], [x1, 0], COLORS.axis);
      this._free(this.grid);
      this.grid = this._buffer(new Float32Array(v), [{ prog: this.pLine, name: "aPos", n: 3 }, { prog: this.pLine, name: "aCol", n: 4 }]);
    }

    reset(redraw = true) {
      this.cam = { yaw: HOME.yaw, pitch: HOME.pitch, zoom: 1, pan: [0, 0] };
      if (redraw) this.draw();
    }

    // ------------------------------------------------------------ disegno
    draw() { this._dirty = true; }

    _loop() {
      if (this._dirty) { this._dirty = false; this._render(); }
      requestAnimationFrame(this._loop);
    }

    _render() {
      const gl = this.gl, c = this.canvas;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.round(c.clientWidth * dpr)), h = Math.max(1, Math.round(c.clientHeight * dpr));
      if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      if (!this.face) return;

      const { yaw, pitch, zoom, pan } = this.cam;
      const a = yaw * Math.PI / 180, e = pitch * Math.PI / 180;
      const dir = [Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e)];
      const R = this.radius;
      const eye = [this.center[0] + dir[0] * R * 4, this.center[1] + dir[1] * R * 4, this.center[2] + dir[2] * R * 4];
      const view = lookAt(eye, this.center, [0, 0, 1]);
      const half = (R * 1.12) / zoom, aspect = w / h;
      const hw = aspect >= 1 ? half * aspect : half, hh = aspect >= 1 ? half : half / aspect;
      const proj = ortho(-hw - pan[0], hw - pan[0], -hh - pan[1], hh - pan[1], R * 0.5, R * 8);
      const mvp = mul(proj, view);
      this._px = (2 * hh) / h;                       // mm per pixel (per lo spostamento)

      gl.enable(gl.DEPTH_TEST);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

      // griglia sotto, senza scrivere la profondità
      gl.useProgram(this.pLine);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.pLine, "uMVP"), false, mvp);
      if (pitch > 0) {
        gl.depthMask(false);
        gl.bindVertexArray(this.grid.vao);
        gl.drawArrays(gl.LINES, 0, this.grid.count);
        gl.depthMask(true);
      }

      // facce, spinte indietro perché gli spigoli restino sopra
      gl.useProgram(this.pFace);
      gl.uniformMatrix4fv(gl.getUniformLocation(this.pFace, "uMVP"), false, mvp);
      gl.uniform3fv(gl.getUniformLocation(this.pFace, "uLight"), norm([dir[0] - 0.3, dir[1] - 0.5, dir[2] + 0.8]));
      gl.enable(gl.POLYGON_OFFSET_FILL);
      gl.polygonOffset(1.5, 2);
      gl.bindVertexArray(this.face.vao);
      gl.drawArrays(gl.TRIANGLES, 0, this.face.count);
      gl.disable(gl.POLYGON_OFFSET_FILL);

      // spigoli
      gl.useProgram(this.pLine);
      gl.bindVertexArray(this.lines.vao);
      gl.drawArrays(gl.LINES, 0, this.lines.count);

      // strumento: solo contorno, sempre visibile
      gl.disable(gl.DEPTH_TEST);
      gl.bindVertexArray(this.ghost.vao);
      gl.drawArrays(gl.LINES, 0, this.ghost.count);
      gl.bindVertexArray(null);
    }

    // ------------------------------------------------------------ interazione
    _bind() {
      const c = this.canvas, pts = new Map();
      let last = null, pinch = null;
      c.addEventListener("contextmenu", (e) => e.preventDefault());
      c.addEventListener("pointerdown", (e) => {
        c.setPointerCapture(e.pointerId);
        pts.set(e.pointerId, [e.clientX, e.clientY]);
        last = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
        if (pts.size === 2) {
          const [p, q] = [...pts.values()];
          pinch = { d: Math.hypot(p[0] - q[0], p[1] - q[1]), zoom: this.cam.zoom };
        }
      });
      c.addEventListener("pointermove", (e) => {
        if (!pts.has(e.pointerId)) return;
        pts.set(e.pointerId, [e.clientX, e.clientY]);
        if (pts.size === 2 && pinch) {
          const [p, q] = [...pts.values()];
          this.cam.zoom = Math.min(12, Math.max(0.4, pinch.zoom * Math.hypot(p[0] - q[0], p[1] - q[1]) / pinch.d));
          this.draw();
          return;
        }
        if (!last) return;
        const dx = e.clientX - last.x, dy = e.clientY - last.y;
        last.x = e.clientX; last.y = e.clientY;
        if (last.pan) {
          const k = (this._px || 1) * Math.min(window.devicePixelRatio || 1, 2);
          this.cam.pan[0] += dx * k; this.cam.pan[1] -= dy * k;
        } else {
          this.cam.yaw -= dx * 0.4;
          this.cam.pitch = Math.min(89, Math.max(-10, this.cam.pitch + dy * 0.3));
        }
        this.draw();
      });
      const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) last = null; };
      c.addEventListener("pointerup", up);
      c.addEventListener("pointercancel", up);
      c.addEventListener("wheel", (e) => {
        e.preventDefault();
        this.cam.zoom = Math.min(12, Math.max(0.4, this.cam.zoom * Math.exp(-e.deltaY * 0.0015)));
        this.draw();
      }, { passive: false });
      c.addEventListener("dblclick", () => this.reset());
      c.tabIndex = 0;
      c.addEventListener("keydown", (e) => {
        const k = { ArrowLeft: [8, 0], ArrowRight: [-8, 0], ArrowUp: [0, 5], ArrowDown: [0, -5] }[e.key];
        if (k) {
          e.preventDefault();
          this.cam.yaw += k[0];
          this.cam.pitch = Math.min(89, Math.max(-10, this.cam.pitch + k[1]));
          this.draw();
        } else if (e.key === "+" || e.key === "-") {
          this.cam.zoom = Math.min(12, Math.max(0.4, this.cam.zoom * (e.key === "+" ? 1.2 : 1 / 1.2)));
          this.draw();
        } else if (e.key === "0") this.reset();
      });
    }
  }

  window.StandViewer = StandViewer;
})();

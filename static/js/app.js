/* لوطی — رفتارهای کوچک رابط کاربری (Alpine.js + HTMX) */
(function () {
  const FA = "۰۱۲۳۴۵۶۷۸۹";
  const toFa = (s) => String(s).replace(/\d/g, (d) => FA[d]);
  const toEn = (s) => String(s).replace(/[۰-۹]/g, (d) => FA.indexOf(d)).replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  const money = (n) => toFa(Math.round(Number(n) || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "٬"));
  window.gm = { toFa, toEn, money };

  document.addEventListener("alpine:init", () => {
    /* حالت روز/شب — انتخاب کاربر در localStorage؛ اگر انتخابی نکرده، از تنظیم سیستم پیروی می‌کند */
    const root = document.documentElement;
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    const sysDark = matchMedia("(prefers-color-scheme: dark)");
    const saved = () => { try { return localStorage.getItem("gm-theme"); } catch (e) { return null; } };
    Alpine.store("theme", {
      dark: root.dataset.theme === "dark",
      apply(on) {
        this.dark = on;
        root.dataset.theme = on ? "dark" : "light";
        if (themeMeta) themeMeta.content = on ? "#15100D" : "#FAF6F0";
      },
      set(on, from) {
        if (on === this.dark) return;
        try { localStorage.setItem("gm-theme", on ? "dark" : "light"); } catch (e) {}
        const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
        if (reduce) return this.apply(on);
        if (!document.startViewTransition) {
          root.classList.add("theme-fading");
          this.apply(on);
          return setTimeout(() => root.classList.remove("theme-fading"), 500);
        }
        // دایره تم جدید از مرکز همان کلیدی که زده شد باز می‌شود تا گوشه‌های صفحه
        const r = from && from.closest(".theme-sw") ? from.closest(".theme-sw").getBoundingClientRect() : null;
        const x = r ? r.left + r.width / 2 : innerWidth / 2;
        const y = r ? r.top + r.height / 2 : 0;
        const end = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
        root.classList.add("vt-theme");
        const vt = document.startViewTransition(() => this.apply(on));
        vt.finished.finally(() => root.classList.remove("vt-theme"));
        vt.ready.then(() => root.animate(
          { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${end}px at ${x}px ${y}px)`] },
          { duration: 700, easing: "cubic-bezier(.65,0,.35,1)", pseudoElement: "::view-transition-new(root)" },
        )).catch(() => {});
      },
    });
    sysDark.addEventListener("change", (e) => { if (!saved()) Alpine.store("theme").apply(e.matches); });

    /* پیام‌های کوتاه (Toast) */
    Alpine.store("toasts", {
      items: [],
      push(kind, title, text = "") {
        const id = Date.now() + Math.random();
        this.items.push({ id, kind, title, text });
        setTimeout(() => this.remove(id), 6000);
      },
      remove(id) { this.items = this.items.filter((t) => t.id !== id); },
    });

    /* پنجره تأیید عملیات‌های برگشت‌ناپذیر — فرم‌هایی که data-confirm دارند */
    Alpine.store("confirm", {
      open: false, title: "", text: "", ok: "تأیید", tone: "", form: null,
      ask(form) {
        this.form = form;
        this.title = form.dataset.confirm;
        this.text = form.dataset.confirmText || "";
        this.ok = form.dataset.confirmOk || "بله، انجام بده";
        this.tone = form.dataset.confirmTone || "";
        this.open = true;
      },
      accept() { const f = this.form; this.open = false; if (f) { f.dataset.confirmed = "1"; f.requestSubmit ? f.requestSubmit() : f.submit(); } },
    });

    /* نمایش نتایج آگهی: چند ستونه (grid) یا تک ستونه (list) — روی html[data-view] و در localStorage می‌ماند */
    Alpine.data("viewToggle", () => ({
      v: document.documentElement.dataset.view === "list" ? "list" : "grid",
      init() {
        this.$watch("v", (v) => {
          try { localStorage.setItem("gm-view", v); } catch (e) {}
          const apply = () => { document.documentElement.dataset.view = v; };
          if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
            const t = document.startViewTransition(apply);
            t.ready.catch(() => {}); // کلیک پشت‌سرهم ترنزیشن قبلی را رد می‌کند؛ خطا نیست
          } else apply();
        });
      },
    }));

    /* دراپ‌داون انتخابی (جای select بومی): مقدار در input مخفی می‌نشیند و فرم را دوباره می‌فرستد؛
       با فلش بالا/پایین بین گزینه‌ها می‌رود و Escape آن را می‌بندد */
    Alpine.data("ddSelect", (val = "") => ({
      open: false, val,
      toggle() { this.open = !this.open; if (this.open) this.$nextTick(() => (this.opts().find((o) => o.getAttribute("aria-selected") === "true") || this.opts()[0])?.focus()); },
      opts() { return [...this.$root.querySelectorAll(".dd-opt")]; },
      move(step) { const o = this.opts(), i = o.indexOf(document.activeElement); o[(i + step + o.length) % o.length]?.focus(); },
      pick(v, el) {
        this.open = false; this.$refs.btn.focus();
        if (v === this.val) return;
        this.val = v; this.$refs.label.textContent = el.textContent.trim();
        this.$nextTick(() => { const f = this.$refs.input.form; if (f) f.requestSubmit ? f.requestSubmit() : f.submit(); });
      },
    }));

    /* هدر (CardNav): با اسکرول به پایین کنار می‌رود و با اسکرول به بالا برمی‌گردد؛
       همبرگر کارت را تا قد محتوا باز می‌کند (دسکتاپ ۲۶۰ پیکسل، موبایل به اندازه کارت‌های روی هم) */
    Alpine.data("siteHeader", () => ({
      menu: false, user: false, notif: false, hidden: false, scrolled: false, lastY: 0,
      init() {
        const reduce = matchMedia("(prefers-reduced-motion: reduce)");
        this.lastY = scrollY;
        this.scrolled = scrollY > 8;
        addEventListener("scroll", () => {
          const y = Math.max(0, scrollY), d = y - this.lastY;
          if (this.scrolled !== y > 8) this.scrolled = y > 8;
          root.classList.toggle("at-foot", y + innerHeight >= root.scrollHeight - 48);
          if (Math.abs(d) < 6) return;
          this.lastY = y;
          // ته صفحه نوارها برمی‌گردند تا جای خالیِ زیر فوتر (فضای نوار پایین) پر بماند
          const atEnd = y + innerHeight >= root.scrollHeight - 48;
          const hide = !reduce.matches && d > 0 && y > 120 && !atEnd && !this.user && !this.notif && !this.menu;
          if (hide !== this.hidden) { this.hidden = hide; root.classList.toggle("hdr-hidden", hide); }
        }, { passive: true });
        this.$watch("menu", (open) => {
          if (open) { this.user = this.notif = false; this.hidden = false; root.classList.remove("hdr-hidden"); }
          this.fit();
        });
        const show = (v) => { if (v) { this.menu = false; this.hidden = false; root.classList.remove("hdr-hidden"); } };
        this.$watch("user", show);
        this.$watch("notif", show);
        addEventListener("resize", () => this.menu && this.fit(), { passive: true });
      },
      // همان calculateHeight اصل: روی موبایل کارت‌ها زیر هم‌اند و قد از محتوا می‌آید
      fit() {
        const nav = this.$refs.nav;
        if (!this.menu) { nav.style.height = ""; return; }
        // offsetTop جابه‌جایی translate کارت‌ها را نمی‌بیند؛ پس قد واقعی چیدمان اندازه گرفته می‌شود
        const last = this.$refs.cards.lastElementChild;
        nav.style.height = (matchMedia("(max-width: 768px)").matches ? 60 + last.offsetTop + last.offsetHeight + 10 : 260) + "px";
      },
    }));

    /* صحنه هیرو: یک نور ملایم دنبال نشانگر موس می‌آید (فقط موس؛ در حالت کاهش حرکت خاموش) */
    Alpine.data("heroSpot", () => ({
      move(e) {
        if (e.pointerType !== "mouse" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        const r = this.$el.getBoundingClientRect();
        this.$el.style.setProperty("--mx", ((e.clientX - r.left) / r.width * 100).toFixed(1) + "%");
        this.$el.style.setProperty("--my", ((e.clientY - r.top) / r.height * 100).toFixed(1) + "%");
      },
    }));

    /* پالت جستجو */
    Alpine.data("palette", () => ({
      open: false,
      show() { this.open = true; this.$nextTick(() => this.$refs.q && this.$refs.q.focus()); },
      onKey(e) {
        if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "ل")) { e.preventDefault(); this.open ? (this.open = false) : this.show(); }
        if (e.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) { e.preventDefault(); this.show(); }
      },
      move(dir) {
        const items = [...this.$root.querySelectorAll("[data-pal-item]")];
        if (!items.length) return;
        let i = items.indexOf(document.activeElement);
        i = i === -1 ? (dir > 0 ? 0 : items.length - 1) : (i + dir + items.length) % items.length;
        items[i].focus();
      },
    }));

    /* ورودی مبلغ با جداکننده هزارگان و نمایش «به حروف تقریبی» */
    Alpine.data("moneyInput", (initial = "") => ({
      raw: toEn(initial).replace(/\D/g, ""),
      get shown() { return this.raw ? money(this.raw) : ""; },
      get value() { return Number(this.raw || 0); },
      set(v) { this.raw = toEn(v).replace(/\D/g, "").slice(0, 11); },
      get words() {
        const n = this.value;
        if (!n) return "";
        if (n >= 1e9) return toFa((n / 1e9).toFixed(n % 1e9 ? 1 : 0)) + " میلیارد تومان";
        if (n >= 1e6) return toFa((n / 1e6).toFixed(n % 1e6 ? 1 : 0)) + " میلیون تومان";
        if (n >= 1e3) return toFa(Math.round(n / 1e3)) + " هزار تومان";
        return toFa(n) + " تومان";
      },
    }));

    /* محاسبه کارمزد واسط — همان فرمول سمت سرور */
    Alpine.data("feeCalc", (cfg) => ({
      price: cfg.price || 0, payer: cfg.payer || "buyer",
      get fee() {
        let f = Math.min(Math.max(this.price * cfg.percent / 100, cfg.min), cfg.max);
        return Math.round(f / 1000) * 1000;
      },
      get buyerTotal() { return this.price + (this.payer === "buyer" ? this.fee : this.payer === "split" ? this.fee - Math.floor(this.fee / 2) : 0); },
      get sellerGets() { return this.price - (this.payer === "seller" ? this.fee : this.payer === "split" ? Math.floor(this.fee / 2) : 0); },
      m: money,
    }));

    /* شمارش معکوس مهلت‌ها */
    Alpine.data("countdown", (iso) => ({
      left: 0, timer: null,
      init() { const end = new Date(iso).getTime(); const tick = () => { this.left = Math.max(0, end - Date.now()); }; tick(); this.timer = setInterval(tick, 1000); },
      destroy() { clearInterval(this.timer); },
      get label() {
        if (this.left <= 0) return "مهلت تمام شد";
        const s = Math.floor(this.left / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        return toFa(`${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`);
      },
    }));

    /* کد یک‌بارمصرف: پرش خودکار، چسباندن و ارسال خودکار */
    Alpine.data("otp", (len = 4) => ({
      resendIn: 60,
      init() {
        const t = setInterval(() => { this.resendIn > 0 ? this.resendIn-- : clearInterval(t); }, 1000);
        this.$nextTick(() => this.inputs()[0].focus());
      },
      inputs() { return [...this.$root.querySelectorAll(".otp-input")]; },
      onInput(e, i) {
        const el = e.target; el.value = toEn(el.value).replace(/\D/g, "").slice(-1);
        if (el.value && i < len - 1) this.inputs()[i + 1].focus();
        if (this.inputs().every((x) => x.value)) this.$root.requestSubmit();
      },
      onKey(e, i) { if (e.key === "Backspace" && !e.target.value && i > 0) this.inputs()[i - 1].focus(); },
      onPaste(e) {
        const v = toEn(e.clipboardData.getData("text")).replace(/\D/g, "").slice(0, len);
        if (!v) return; e.preventDefault();
        this.inputs().forEach((x, i) => (x.value = v[i] || ""));
        if (v.length === len) this.$root.requestSubmit();
      },
      fill(code) {
        const v = toEn(String(code));
        this.inputs().forEach((x, i) => (x.value = v[i] || ""));
        this.$root.requestSubmit();
      },
      get resendLabel() { return toFa(this.resendIn); },
    }));

    /* بارگذاری تصویر با پیش‌نمایش و کشیدن‌ورهاکردن */
    Alpine.data("dropzone", (max = 6) => ({
      previews: [], over: false, error: "",
      pick(files) {
        const dt = new DataTransfer();
        [...files].filter((f) => f.type.startsWith("image/")).slice(0, max).forEach((f) => dt.items.add(f));
        this.error = files.length > max ? `حداکثر ${toFa(max)} تصویر` : "";
        this.$refs.file.files = dt.files;
        this.previews.forEach((p) => URL.revokeObjectURL(p.url));
        this.previews = [...dt.files].map((f) => ({ name: f.name, url: URL.createObjectURL(f) }));
      },
      drop(e) { this.over = false; this.pick(e.dataTransfer.files); },
      removeAt(i) { const files = [...this.$refs.file.files]; files.splice(i, 1); this.pick(files); },
    }));

    /* کپی در کلیپ‌بورد */
    Alpine.data("copy", (text) => ({
      done: false,
      run() { navigator.clipboard.writeText(text).then(() => { this.done = true; setTimeout(() => (this.done = false), 1600); }); },
    }));

    /* محافظ گفتگو: هشدار پیش از ارسال راه ارتباطی */
    Alpine.data("chatGuard", () => ({
      text: "",
      get risky() {
        const t = toEn(this.text);
        return /(09\d{2}[\s-]?\d{3}[\s-]?\d{4})|(@[a-z][\w.]{3,})|t\.me|wa\.me|تلگرام|واتس|اینستا|telegram|whatsapp|instagram/i.test(t);
      },
    }));
  });

  /* رهگیری ارسال فرم‌های حساس */
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (f.matches("form[data-confirm]") && f.dataset.confirmed !== "1" && window.Alpine) {
      e.preventDefault();
      e.stopImmediatePropagation();
      Alpine.store("confirm").ask(f);
    } else if (f.dataset.confirmed === "1") {
      delete f.dataset.confirmed;
    }
  }, true);

  /* رفتن به صفحه دیگر: نوار بارگذاری بالای صفحه تا رسیدن صفحه تازه */
  const navStart = () => document.documentElement.classList.add("is-navigating");
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target && a.target !== "_self" || a.hasAttribute("download") || a.matches("[hx-get],[hx-post],[hx-boost]")) return;
    const u = new URL(a.href, location.href);
    if (u.origin !== location.origin || (u.pathname === location.pathname && u.search === location.search)) return;
    navStart();
  });
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (!e.defaultPrevented && !f.matches("[hx-get],[hx-post],[hx-put],[hx-delete]") && f.target !== "_blank") navStart();
  });
  addEventListener("pageshow", () => document.documentElement.classList.remove("is-navigating"));

  /* محتوای تازه HTMX (صفحه بعد آگهی‌ها، فیلتر، پیام) نرم و پلکانی وارد می‌شود */
  let batch = 0, batchReset = 0;
  document.addEventListener("htmx:load", (e) => {
    const el = e.detail.elt;
    if (!el || el === document.body || !el.animate || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const cards = el.matches(".go-card") ? [el] : [...el.querySelectorAll(".go-card")].slice(0, 12);
    const targets = cards.length ? cards : [el];
    targets.forEach((t) => {
      t.animate(
        [{ opacity: 0, transform: "translateY(12px) scale(.98)" }, { opacity: 1, transform: "none" }],
        { duration: 450, easing: "cubic-bezier(.32,.72,0,1)", delay: Math.min(batch++, 12) * 40, fill: "backwards" },
      );
    });
    cancelAnimationFrame(batchReset);
    batchReset = requestAnimationFrame(() => (batch = 0));
  });

  /* جهت نوشتن خودکار: متن فارسی از راست و متن انگلیسی از چپ نوشته می‌شود (dir=auto بر اساس اولین حرف)؛
     ورودی خالی راست‌چین می‌ماند (CSS با :placeholder-shown). ورودی‌هایی که از اول لاتین‌اند (.ltr یا dir صریح) دست نمی‌خورند. */
  const AUTO_DIR = "input:not([type]), input[type=text], input[type=search], textarea";
  const autoDir = (el) => {
    if (!el.matches || !el.matches(AUTO_DIR) || "autodir" in el.dataset || el.classList.contains("ltr") || el.hasAttribute("dir")) return;
    el.dataset.autodir = "";
    el.dir = "auto";
    if (!el.hasAttribute("placeholder")) el.placeholder = " ";
  };
  const scanDir = (root) => root && root.querySelectorAll && root.querySelectorAll(AUTO_DIR).forEach(autoDir);
  document.addEventListener("DOMContentLoaded", () => scanDir(document));
  document.addEventListener("htmx:load", (e) => scanDir(e.detail.elt));
  document.addEventListener("focusin", (e) => autoDir(e.target));

  /* خطای شبکه در HTMX */
  document.addEventListener("htmx:responseError", () => {
    window.Alpine && Alpine.store("toasts").push("error", "مشکلی پیش آمد", "لطفاً دوباره تلاش کنید.");
  });
  document.addEventListener("htmx:sendError", () => {
    window.Alpine && Alpine.store("toasts").push("error", "اتصال برقرار نشد", "اینترنت خود را بررسی کنید.");
  });
})();

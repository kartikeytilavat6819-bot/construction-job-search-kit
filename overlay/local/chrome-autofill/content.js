// career-ops Autofill: runs inside every frame of an armed tab.
// Scrolls to each field and fills it so you can watch: amber while working, green when done,
// blue for uploads (hover a field to see which profile.json key it came from). The top frame
// shows a panel listing what was filled and what still "Needs you".
//
// Works on plain forms and on the widgets the big application systems use: Workday buttons
// that open listboxes and its search prompts, react-select (Greenhouse), ARIA comboboxes
// (Oracle, Paylocity, ADP, UKG), radio groups, fields inside shadow DOM (SmartRecruiters),
// fields whose only label is nearby text (Cornerstone, Taleo, Paylocity), and forms inside
// iframes (iCIMS). It never clicks Next, Submit, Save or any other button except a dropdown's
// own opener and its options, and it pauses while you are typing or clicking.
(() => {
  if (window.__coafAutofill) return; // already running in this document (same extension load)
  window.__coafAutofill = true;
  const TOP = window === window.top;
  const RUN = Math.random().toString(36).slice(2);
  document.documentElement.setAttribute("data-coaf-run", RUN); // a newer copy (after a self-update) takes over

  // ---------- small helpers ----------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const norm = (s) => clean(String(s || "").toLowerCase().replace(/['’]/g, "").replace(/[^a-z0-9]+/g, " "));
  const stripReq = (s) => clean((s || "").replace(/[*✱]/g, " ").replace(/\((required|optional)\)/gi, " ").replace(/\brequired\b\s*$/i, ""));
  const splitAttr = (s) => (s || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[._\-]+/g, " ").toLowerCase();
  const GREEN = "#16a34a", BLUE = "#2563eb", AMBER = "#f59e0b", PURPLE = "#9333ea";
  const alive = () => !stopped && !!chrome.runtime?.id && document.documentElement.getAttribute("data-coaf-run") === RUN;

  let cfg = null, stopped = false, lastUser = 0;
  const done = new WeakSet(); // controls already handled (filled, or skipped on purpose)
  const tries = new WeakMap(); // dropdowns: attempts so far (options sometimes load late)
  const flags = new WeakMap(); // control -> reason you must answer it yourself
  const uploaded = new Set(); // "resume" / "cover": once per page, even if the site re-renders the input
  const filled = []; // {time, label, key, value}
  const infoCache = new WeakMap();

  const send = (msg) =>
    chrome.runtime.sendMessage(msg).then((r) => (r && r.ok ? r.result : null)).catch(() => null);

  // Your own typing/clicking pauses autofill for a moment so it never fights you.
  for (const ev of ["keydown", "mousedown", "touchstart"]) {
    document.addEventListener(ev, (e) => { if (e.isTrusted && !e.target?.closest?.("#__coaf_panel")) lastUser = Date.now(); }, true);
  }
  const userBusy = () => Date.now() - lastUser < 2500;

  // ---------- DOM access that also sees open shadow roots ----------
  function roots() {
    const out = [document];
    for (let i = 0; i < out.length; i++) {
      for (const el of out[i].querySelectorAll("*")) if (el.shadowRoot) out.push(el.shadowRoot);
    }
    return out;
  }
  const deepAll = (sel, rs = roots()) => rs.flatMap((r) => [...r.querySelectorAll(sel)]);
  const parentOf = (n) => n.parentElement || (n.getRootNode && n.getRootNode().host) || null;
  function byId(el, id) {
    const r = el.getRootNode();
    return (r.getElementById && r.getElementById(id)) || document.getElementById(id);
  }
  function visible(el) {
    if (!el || !el.getClientRects().length) return false;
    const st = getComputedStyle(el);
    return st.visibility !== "hidden" && st.display !== "none";
  }
  // Visible itself, or (for styled-away inputs like file/radio) its nearby wrapper is.
  function shown(el) {
    if (visible(el) && el.getBoundingClientRect().width > 1) return true;
    for (let n = parentOf(el), i = 0; n && n.nodeType === 1 && i < 3; n = parentOf(n), i++) if (visible(n)) return true;
    return false;
  }

  const VALUE_SEL = "[class*=single-value],[class*=singleValue],[class*=multi-value],[class*=multiValue],[data-automation-id=selectedItem],[class*=selected-item]";
  const SKIP_TEXT = "select,option,datalist,script,style,noscript,template,[role=listbox],[role=option],#__coaf_panel,[class*=placeholder]," + VALUE_SEL;
  // Readable text of a node, skipping option lists, scripts, a widget's current value and hidden parts.
  function textOf(node) {
    const parts = [];
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, {
      acceptNode(t) {
        const p = t.parentElement;
        if (!p || p.closest(SKIP_TEXT)) return NodeFilter.FILTER_REJECT;
        if (!p.getClientRects().length) return NodeFilter.FILTER_REJECT;
        return t.data.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });
    while (walker.nextNode()) parts.push(walker.currentNode.data);
    return clean(parts.join(" "));
  }

  // ---------- which controls exist ----------
  const CONTROL_SEL = [
    "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=image]):not([type=reset])",
    "select", "textarea", "[role=combobox]", "button[aria-haspopup=listbox]", "[role=radio]",
  ].join(",");
  // One entry per thing you answer: a radio group counts once.
  function groupKey(el) {
    if (el.type === "radio" && el.name) return "r:" + el.name;
    if (el.getAttribute("role") === "radio") return el.closest("[role=radiogroup]") || el;
    return el;
  }
  function groupsIn(node) {
    const seen = new Set();
    for (const c of node.querySelectorAll(CONTROL_SEL)) {
      if (c.closest("#__coaf_panel") || (c.type !== "file" && !shown(c))) continue;
      seen.add(groupKey(c));
      if (seen.size > 1) break;
    }
    return seen.size;
  }

  const GENERIC = /^(select( one|\.\.\.| an option)?|choose( one| an option)?|please select|search|type to search|start typing.*|--+|attach|upload|browse|none selected|mm\/?dd\/?yyyy|mm\/?yyyy)$/i;

  // Label from the text around the field (Cornerstone, Taleo, Paylocity have no <label>).
  function nearbyText(el) {
    let n = parentOf(el), lastSingle = null;
    for (let i = 0; n && n !== document.body && n.nodeType === 1 && i < 6; n = parentOf(n), i++) {
      if (groupsIn(n) > 1) break;
      lastSingle = n;
      const t = stripReq(textOf(n));
      if (t && !GENERIC.test(t) && t.length < 250) return t;
    }
    // Label in an earlier sibling (table cells, label-less rows)
    for (let s = (lastSingle || el).previousElementSibling, i = 0; s && i < 3; s = s.previousElementSibling, i++) {
      if (s.querySelector && s.querySelector(CONTROL_SEL)) break;
      const t = stripReq(textOf(s));
      if (t && !GENERIC.test(t) && t.length < 250) return t;
    }
    return "";
  }

  function labelFor(el) {
    const r = el.getRootNode();
    const parts = [];
    if (el.id) {
      const l = (r.querySelector && r.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) parts.push(textOf(l) || l.innerText);
    }
    const wrap = el.closest("label");
    if (wrap && wrap.querySelectorAll(CONTROL_SEL).length <= 1) parts.push(textOf(wrap));
    const by = el.getAttribute("aria-labelledby");
    if (by) parts.push(by.split(/\s+/).map((i) => byId(el, i)).filter(Boolean).map((n) => textOf(n) || n.innerText || "").join(" "));
    parts.push(el.getAttribute("aria-label") || "");
    if (r instanceof ShadowRoot) {
      const h = r.host;
      parts.push(h.getAttribute("label") || h.getAttribute("aria-label") || "");
      if (h.id) { const l = h.getRootNode().querySelector?.(`label[for="${CSS.escape(h.id)}"]`); if (l) parts.push(textOf(l)); }
    }
    for (const p of parts) {
      const t = stripReq(p);
      if (t && !GENERIC.test(t)) return t;
    }
    const fs = el.closest("fieldset");
    if (fs && groupsIn(fs) <= 1) { const lg = fs.querySelector("legend"); if (lg && textOf(lg)) return stripReq(textOf(lg)); }
    const near = nearbyText(el);
    if (near) return near;
    for (const a of ["title", "placeholder"]) {
      const t = stripReq(el.getAttribute(a));
      if (t && !GENERIC.test(t)) return t;
    }
    return "";
  }

  // The heading of the form section a field sits in ("Work Experience", "References", ...).
  function sectionOf(el) {
    for (let n = parentOf(el), i = 0; n && n.nodeType === 1 && i < 12; n = parentOf(n), i++) {
      const hs = n.querySelectorAll("h2,h3,h4,h5,legend,[role=heading],[data-automation-id*=Heading i],[class*=section-title i],[class*=sectionTitle]");
      let last = null;
      for (const h of hs) if (!h.contains(el) && h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) last = h;
      if (last && textOf(last)) return norm(textOf(last));
    }
    return "";
  }
  function attrBlob(el) {
    const own = ["name", "id", "data-automation-id", "data-qa", "data-testid", "autocomplete", "formcontrolname"]
      .map((a) => el.getAttribute(a) || "").join(" ");
    let anc = "";
    for (let n = parentOf(el), i = 0; n && n.nodeType === 1 && i < 8; n = parentOf(n), i++) {
      anc += " " + (n.id || "") + " " + (n.getAttribute("data-automation-id") || "");
    }
    return { own: splitAttr(own), anc: splitAttr(anc) };
  }
  function rawLabelText(el) {
    if (el.id) { const l = el.getRootNode().querySelector?.(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText; }
    for (let n = parentOf(el), i = 0; n && n.nodeType === 1 && i < 4; n = parentOf(n), i++) {
      if (groupsIn(n) > 1) break;
      const t = n.innerText || "";
      if (t.trim()) return t.slice(0, 300);
    }
    return el.getAttribute("aria-label") || "";
  }
  function describe(el) {
    if (infoCache.has(el)) return infoCache.get(el);
    const label = labelFor(el);
    const { own, anc } = attrBlob(el);
    const info = {
      label,
      text: norm(label),
      attrs: own,
      area: sectionOf(el) + " " + anc,
      required: el.required || el.getAttribute("aria-required") === "true" || /[*✱]|\(required\)/i.test(rawLabelText(el)),
      ac: (el.getAttribute("autocomplete") || "").toLowerCase(),
    };
    infoCache.set(el, info);
    return info;
  }

  // ---------- what a field is asking for ----------
  const OTHER_PARTY = /reference|emergency|work experience|work history|employment history|previous employ|prior employ|employer information|supervisor|military/;
  const EDUCATION = /education|school|academic|universit|college/;
  const NOT_YOURS = /\b(company|employer|business|office|school|universit|college|institution|reference|referee|supervisor|manager|emergency|spouse|parent|guardian|recruiter|agency)/;
  const PERSONAL = new Set(["first_name", "last_name", "full_name", "preferred_name", "email", "phone", "phone_type", "phone_country_code", "linkedin", "website",
    "street_address", "address_line2", "zip", "location", "city", "state", "country"]);
  const YESNO = new Set(["require_sponsorship", "authorized_to_work_us", "willing_to_relocate", "over_18", "has_drivers_license",
    "previously_employed_here", "relatives_at_company", "has_noncompete", "essential_functions", "family_gov_employed",
    "gov_employed_now", "gov_employed_recent", "owned_business", "sms_consent", "applied_before"]);
  // Keys a question-style field ("What is your GPA?") may get.
  const ANSWER_KEYS = new Set(["gpa", "salary_expectation", "start_date", "how_did_you_hear", "graduation_date", "school", "degree",
    "discipline", "current_title", "current_company", "languages", "licenses", "linkedin", "website", "location", "city", "country", ...YESNO]);
  // short answers that may sit in a multi-line box (Lever puts "Preferred First Name" in a textarea)
  const TEXTAREA_KEYS = new Set(["preferred_name", "current_company", "current_title", "languages", "licenses", "summary", "headline", "linkedin", "website", "location"]);
  // filled from data rather than profile.json
  function derived(k, el, info) {
    switch (k) {
      case "salary_expectation": return salaryText(el, info);
      case "salary_type": { const s = cfg.extra && cfg.extra.salary_max; return s ? (s.period === "hour" ? "Hourly" : "Annual") : null; }
      case "summary": return cfg.profile.summary;
      case "applied_before": return cfg.extra ? cfg.extra.applied_before : null; // from your tracker: another application at this company
      case "today": { if (!EEO_AREA.test(info.area) && !/disabilit|veteran|self identif/.test(info.area + " " + info.attrs)) return null;
        const d = new Date(); return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}/${d.getFullYear()}`; }
    }
    return null;
  }

  const QUESTION_RULES = [
    [/^(?!.*without).*(requir|need|commence).{0,80}sponsor/, "require_sponsorship"], // "now or in the future require ... sponsorship"
    [/without\b.{0,40}\bsponsor/, "!ambiguous"],
    [/sponsor|h ?1 ?b|work visa|visa (status|support|transfer)|immigration (support|status)/, "require_sponsorship"],
    [/authori[sz]ed to work|legally (authori[sz]ed|eligible|permitted|able)|eligible to work|right to work|work authori[sz]ation|permitted to work|lawfully/, "authorized_to_work_us"],
    [/essential functions|reasonable accommodation/, "essential_functions"],
    [/(family|relative|parent|sibling).*(government|public)/, "family_gov_employed"],
    [/currently (employed|working) (by|for|at) .*(public|government|agency)/, "gov_employed_now"],
    [/(employed|worked) (by|for|at) .*(public|government|agency)|(public|government).*(last|past) (two|2|\d+) years/, "gov_employed_recent"],
    [/owned (any|a) business|business owner|own(ed)? .{0,40}business/, "owned_business"],
    [/\b(text|sms)\b.*(you|message|permission)|permission to text/, "sms_consent"],
    [/(have|did) you (ever )?(previously )?(applied|submitted an application)|previously applied|applied (for a (job|position) )?(with|to|at) (us|.{0,40}) (before|previously)/, "applied_before"],
    [/relocat/, "willing_to_relocate"],
    [/\b18\b.*(years|older|age)|age of 18|at least 18|over 18/, "over_18"],
    [/commercial|\bcdl\b|class [abc]\b|dot medical|chauffeur|hazmat/, null], // a CDL is not your regular license
    [/driver s licen[sc]e|drivers licen[sc]e/, "has_drivers_license"],
    // "employed by a government agency / any employer" is a different question
    [/^(?!.*(public|government|agency|federal|municipal|institution|military|any employer)).*((ever|previously|currently|formerly|before) (been )?(employed|worked)|(employed|worked) (by|for|at) .* (before|previously)|former employee|current(ly)? (an )?employee)/, "previously_employed_here"],
    [/relative|family member|related to (any|an) /, "relatives_at_company"],
    [/non ?compete|non ?solicit|agreements? with (a |any |your )?(prior|previous|former|current) employer/, "has_noncompete"],
    // voluntary self-identification (EEO): dropdowns/radios only
    [/hispanic|latin[oa]/, "eeo_hispanic"],
    [/\brace\b|ethnicit/, "eeo_race"],
    [/\bgender\b|\bsex\b/, "eeo_gender"],
    [/disabilit/, "eeo_disability"],
    [/veteran/, "eeo_veteran"],
  ];
  const EEO = new Set(["eeo_hispanic", "eeo_race", "eeo_gender", "eeo_disability", "eeo_veteran"]);
  const EEO_AREA = /self identification|voluntary|equal (employment )?opportunity|\beeo\b/;
  const FIELD_RULES = [
    [/preferred (first )?name|nick ?name/, "preferred_name"],
    [/preferred|middle|maiden|former name|other name|suffix|prefix|salutation|pronoun/, null],
    [/\bfirst\b.*\bname\b|given name|^first$|\bfname\b/, "first_name"],
    [/\blast\b.*\bname\b|family name|surname|\blname\b/, "last_name"],
    [/^(your |full |legal |candidate |applicant )*name$/, "full_name"],
    [/e ?mail/, "email"],
    [/(phone|mobile|cell)( number)? (device )?type|device type|phone type/, "phone_type"],
    [/^(phone |mobile )?country( phone)? code|^dial|phone country/, "phone_country_code"], // the +1 picker, not the number
    [/^ext(ension)?\b|\bextension$/, null],
    [/phone|mobile|cell|telephone/, "phone"],
    [/linked ?in/, "linkedin"],
    [/website|portfolio|personal (site|url|web)|github/, "website"],
    [/address (line )?2|\bapt\b|apartment|suite|\bunit\b/, "address_line2"],
    [/street|address (line )?1|^address$|mailing address|home address|street address/, "street_address"],
    [/zip|postal/, "zip"],
    [/city.*state|^(current )?location$|location city|where (are|do) you (currently )?(located|live|reside)|current (city|location)/, "location"],
    [/\bcity\b|\btown\b/, "city"],
    [/county/, null],
    [/\bstate\b|province|region/, "state"],
    [/country/, "country"],
    [/school|universit|college|institution/, "school"],
    [/type of degree|degree type|degree level|level of education|highest (level of )?education|^degree|degree( earned| obtained)?$/, "degree"],
    [/discipline|\bmajor\b|field of study|area of study|concentration|program of study/, "discipline"],
    [/\bgpa\b|grade point/, "gpa"],
    [/graduat|completion date|degree date|date (received|earned|completed)/, "graduation_date"],
    [/salary|compensation|pay (rate|expect)|desired pay|expected pay/, "salary_expectation"],
    [/start date|available to start|availability|date available|when (can|could) you start|earliest start/, "start_date"],
    [/how did you (hear|find|learn)|referral source|^source$|where did you (hear|see|find)/, "how_did_you_hear"],
    [/current (job )?title|current position|present (job )?title/, "current_title"],
    [/current (company|employer)|present (company|employer)|^employer$/, "current_company"],
    [/headline/, "headline"],
    [/^(professional |personal )?summary\b|about (you|yourself)|profile summary/, "summary"],
    [/languages?\b/, "languages"],
    [/^(?!.*(driv|class|endorse|cdl|commercial)).*(licen[sc]es?|certifications?)\b.*(hold|held|have|list)|^(list|please list) .*(licen[sc]e|certification)|professional licen[sc]e/, "licenses"],
    [/salary type|pay type|compensation type|pay basis|salary basis/, "salary_type"],
    [/^(salary range|minimum (desired )?salary|maximum (desired )?salary|to)$|desired salary (min|max)/, "salary_expectation"],
    [/^(today s )?date$|^signature date$|^date signed$/, "today"],
  ];
  const AUTOCOMPLETE = {
    "given-name": "first_name", "family-name": "last_name", name: "full_name", email: "email", tel: "phone",
    "tel-national": "phone", "street-address": "street_address", "address-line1": "street_address", "address-level2": "city",
    "address-level1": "state", "postal-code": "zip", country: "country", "country-name": "country", url: "website",
  };
  const isQuestion = (t) => /\?/.test(t) || /^(are|do|does|have|has|will|would|can|could|is|did|were|please (indicate|confirm|select))\b/i.test(t);

  // ---------- work history / education blocks (from cv.md) ----------
  const WORK_AREA = /work experience|work history|employment history|previous employ|prior employ|employer information|employment \d|experience \d/;
  const WORK_RULES = [
    [/currently work|i (currently )?work here|current(ly)? (employed|job|position|role)|present (job|position)|still (employed|working)/, "current"],
    [/reason for leaving|why did you leave/, "reason"],
    [/phone|website|\burl\b|supervisor|manager|salary|\bpay\b|wage|zip|postal|address|county|country|may we contact|currently|reference/, null],
    [/\bstate\b|province/, "state"],
    [/description|responsibilit|duties|achievement|summary|details/, "description"],
    [/job title|position|\btitle\b|\brole\b/, "title"],
    [/company|employer|organi[sz]ation/, "company"],
    [/\bcity\b/, "city"],
    [/location/, "location"],
    [/\bfrom\b|start/, "start"],
    [/\bto\b|\bend\b/, "end"],
  ];
  const EDU_RULES = [
    [/did you graduate|graduated\?|degree (completed|received)\?|completed\?/, "graduated"],
    [/school type|type of school|institution type/, "school_type"],
    [/school|universit|college|institution/, "school"],
    [/type of degree|degree type|degree level|level of education/, "degree_type"], // same entry as "Degree" (Cornerstone has both)
    [/degree/, "degree"],
    [/\bmajor\b|field of study|discipline|area of study|concentration|program/, "discipline"],
    [/\bgpa\b|grade point/, "gpa"],
    [/graduat|completion|date (received|earned|completed)|\bto\b|\bend\b/, "end"],
    [/\bcity\b|location/, "city"],
    [/\bstate\b|province/, "state"],
    [/country/, "country"],
  ];
  // -> {key, block: "work"|"edu"} for a field inside a work-history or education entry, false if it is
  // in such a block but not one we fill, null if it is not in one
  function classifyBlock(info) {
    const ctx = info.area + " " + info.attrs;
    const blk = WORK_AREA.test(ctx) || /work (history|experience)/.test(info.attrs) ? "work"
      : /\beducation|academic (history|background)|schools? attended/.test(info.area) || /education/.test(info.attrs) ? "edu" : null;
    if (!blk) return null;
    const rules = blk === "work" ? WORK_RULES : EDU_RULES;
    for (const s of [info.text, info.attrs]) {
      if (!s) continue;
      for (const [re, key] of rules) if (re.test(s)) return key ? { key, block: blk } : false;
    }
    return false;
  }
  const REPEATS = new Set(["state", "city", "country"]); // an entry can ask these twice (e.g. employer address and location)
  const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  // A cv.md date in the shape this field wants: month only, year only, MM/YYYY or MM/DD/YYYY.
  function dateFor(d, el, info, kind) {
    if (!d) return null;
    const hint = ((el.getAttribute("placeholder") || "") + " " + info.text + " " + info.attrs).toLowerCase();
    const mm = String(d.month || 1).padStart(2, "0");
    const month = /month|\bmm\b$/.test(hint) && !/year|yyyy/.test(hint), year = /year|yyyy$/.test(hint) && !/month|\bmm\b/.test(hint);
    if (month) return kind === "select" ? MONTH_NAMES[(d.month || 1) - 1] : mm;
    if (year) return String(d.year);
    if (/dd/.test(hint)) return `${mm}/01/${d.year}`;
    return `${mm}/${d.year}`;
  }
  // Which entry (1st, 2nd, ...) a block field belongs to: the number in its heading ("Work Experience 2"),
  // else count entries in page order: an entry starts each time its first kind of field ("Job Title") comes round again.
  function blockOrdinals(list) {
    const ord = new Map(), anchor = {}, idx = {}, seen = {};
    for (const el of list) {
      if (el.type === "radio" || el.type === "file" || !(visible(el) || shown(el))) continue;
      const info = describe(el);
      const c = classifyBlock(info);
      if (!c) continue;
      const num = /(?:experience|history|employment|education|school)\s*(\d{1,2})\b/.exec(info.area);
      if (num) { ord.set(el, Number(num[1]) - 1); continue; }
      const b = c.block;
      if (!anchor[b]) anchor[b] = c.key;
      seen[b] ??= new Set();
      if (c.key === anchor[b] || (seen[b].has(c.key) && !REPEATS.has(c.key))) { idx[b] = (idx[b] ?? -1) + 1; seen[b] = new Set(); }
      seen[b].add(c.key);
      ord.set(el, Math.max(idx[b] ?? 0, 0));
    }
    return ord;
  }
  function blockValue(c, i, el, info, kind) {
    const list = c.block === "work" ? cfg.profile.work_history : cfg.profile.education;
    const e = list && list[i || 0];
    if (!e) return null;
    const place = (e.location || "").split(",").map((s) => s.trim());
    switch (c.key) {
      case "start": return dateFor(e.start, el, info, kind);
      case "end": return c.block === "work" && e.current ? null : dateFor(e.end, el, info, kind); // "Present": leave it
      case "city": return place[0] || null;
      case "state": return US_STATES[(place[1] || "").toUpperCase()] ? place[1] : null;
      case "country": { // "Boston, MA" -> United States; "Pune, India" -> India (the last part of a non-US location)
        const last = place[place.length - 1] || "";
        if (!last) return null;
        return place.length > 1 && !US_STATES[last.toUpperCase()] && !/^(usa?|united states.*)$/i.test(last) ? last : "United States";
      }
      case "gpa": return (i || 0) === 0 ? cfg.profile.gpa : null; // profile.json's GPA is for your most recent degree (entry 1)
      case "graduated": return e.expected ? "No" : "Yes";
      case "degree_type": return e.degree;
      case "school_type": return /master|doctor|ph\.?d/i.test(e.degree || "") ? "Graduate School" : "University";
      case "reason": return e.current ? null : /co-?op/i.test(e.title) ? "Co-op term completed" : /intern/i.test(e.title) ? "Internship completed" : null;
      default: return e[c.key] ?? null;
    }
  }

  // -> {key} | {flag: reason} | null
  function classify(info, choice) {
    const blk = classifyBlock(info);
    if (blk) return blk;
    if (blk === false) return null; // e.g. "Company Phone" inside a work-history entry
    const t = info.text;
    const q = isQuestion(info.label);
    const ruleKey = (rules, s) => { for (const [re, key] of rules) if (re.test(s)) return { key }; return null; };
    let hit = null;
    if (q || choice) hit = ruleKey(QUESTION_RULES, t);
    if (hit && hit.key === "!ambiguous") return { flag: "asks about working without sponsorship: answer it yourself" };
    const ac = info.ac.split(" ").pop();
    if (!hit && !q && AUTOCOMPLETE[ac]) hit = { key: AUTOCOMPLETE[ac] };
    if (!hit) hit = ruleKey(FIELD_RULES, t);
    if (!hit && !t) hit = ruleKey(FIELD_RULES, info.attrs); // nothing readable: fall back to name/id attributes
    if (!hit || !hit.key) return null;
    const key = hit.key;
    if (EEO.has(key) && !choice) return null; // never type into a self-identification text box
    if (EEO.has(key)) return { key };
    if (q && !ANSWER_KEYS.has(key)) return null;
    if ((OTHER_PARTY.test(info.area) || OTHER_PARTY.test(info.attrs)) && (PERSONAL.has(key) || key === "current_title")) return null; // a reference's or employer's details
    if (PERSONAL.has(key) && NOT_YOURS.test(t)) return null; // "Company Phone", "School City", "Reference Email"
    if (EDUCATION.test(info.area) && PERSONAL.has(key) && key !== "linkedin") return null; // the school's city/state, not yours
    return { key };
  }

  // ---------- drafted answers from the career-ops report ----------
  const INTENTS = [
    ["hear", /how did you (hear|find|learn)|where did you (hear|see|find)|referral|referred|^source$/],
    ["why_role", /why (are you )?(interested|applying)|interest(ed)? in (this|the) (role|position|job|opportunity)|why (this|the) (role|position|job)|motivat/],
    ["why_company", /why (do you want to |would you like to )?(work|join)|why (us|our company|this company)|what (do you know|attracts you|interests you) about|benefit from|^why \w+$/],
    ["fit", /\bfit\b|qualif|good candidate|why should we|what makes you|strength|stand out|bring to/],
    ["experience", /project|relevant experience|experience (with|in)|tell us about|describe (a|an|your)|example of/],
    ["career", /career|goal|desire to|passion|pursue|long term|five years|5 years/],
  ];
  const intentOf = (t) => (INTENTS.find(([, re]) => re.test(t)) || [null])[0];
  function draftFor(info, isTextarea) {
    const ex = cfg.extra;
    if (!ex) return null;
    const t = info.text;
    if (isTextarea && /cover letter|letter of interest|motivation letter/.test(t) && ex.cover_text) return { text: ex.cover_text, check: false, from: "your cover letter" };
    const drafts = ex.answers || [];
    if (!drafts.length) return null;
    const company = tokens(cfg.job.company || "");
    let want = intentOf(t);
    if (!want && /^why\b/.test(t) && company.some((w) => tokens(t).includes(w))) want = "why_company";
    const qt = new Set(tokens(t).filter((w) => !company.includes(w)));
    const sim = (d) => { const dt = tokens(d.q).filter((w) => !company.includes(w)); const c = dt.filter((w) => qt.has(w)).length; return c / Math.max(Math.min(dt.length, qt.size), 1) + (c >= 2 ? 0.01 * c : 0); };
    let pool = want ? drafts.filter((d) => intentOf(norm(d.q)) === want || (want === "why_company" && /^why\b/.test(norm(d.q)) && company.some((w) => tokens(d.q).includes(w)))) : [];
    let best = pool.sort((a, b) => sim(b) - sim(a))[0];
    if (!best) { // no intent match: plain word overlap, strict
      best = [...drafts].sort((a, b) => sim(b) - sim(a))[0];
      if (!best || sim(best) < 0.6) return null;
    }
    return { text: best.a, check: best.check, from: "the report's draft" };
  }
  function salaryText(el, info) {
    const s = cfg.extra && cfg.extra.salary_max;
    if (!s) return null;
    if (el.type === "number" || /numbers? only|digits only|numeric only|no (symbols|commas)/.test(info.text)) return String(s.amount);
    return "$" + s.amount.toLocaleString("en-US") + (s.period === "hour" ? "/hour" : "");
  }
  async function fillDraft(el, info, d) {
    working(el);
    await sleep(300);
    await typeText(el, d.text, Math.min(cfg.job.speed || 0, 4)); // long text: type fast, but still visibly
    if (!alive()) return;
    if (el.value !== d.text) { setValue(el, d.text); el.dispatchEvent(new Event("input", { bubbles: true, composed: true })); }
    el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    el.blur();
    mark(el, PURPLE, `autofill: drafted from ${d.from}. Read and edit before submitting.`, "#faf5ff");
    filled.push({ time: new Date().toTimeString().slice(0, 8), label: (info.label || "Question").slice(0, 60), key: "draft", value: d.text.slice(0, 80), draft: true, check: d.check });
    report();
  }

  // ---------- picking the right option ----------
  const US_STATES = { AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California", CO: "Colorado", CT: "Connecticut", DE: "Delaware", DC: "District of Columbia", FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana", IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland", MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri", MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey", NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio", OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island", SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah", VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin", WY: "Wyoming" };
  function yesNo(v) {
    if (typeof v === "boolean") return v ? "yes" : "no";
    const s = norm(v);
    return /^yes\b/.test(s) ? "yes" : /^no\b/.test(s) ? "no" : null;
  }
  function aliases(k, v) {
    const s = norm(v);
    const out = [s, norm(String(v).replace(/\(.*?\)/g, ""))];
    if (k === "country" && /united states|^usa?$|^u s a?$/.test(s)) out.push("united states", "united states of america", "usa", "us", "u s", "america");
    if (k === "state") {
      const abbr = Object.keys(US_STATES).find((a) => a.toLowerCase() === s || norm(US_STATES[a]) === s);
      if (abbr) out.push(norm(US_STATES[abbr]), abbr.toLowerCase(), `${abbr.toLowerCase()} ${norm(US_STATES[abbr])}`, `${norm(US_STATES[abbr])} ${abbr.toLowerCase()}`);
    }
    if (k === "degree" && /bachelor/.test(s)) out.push(/engineering/.test(s) ? "bachelor of engineering" : "bachelor of science", "bachelors degree", "bachelors", "bachelor", "be", "b e", "bs", "b s", "btech", "undergraduate degree", "undergraduate");
    if (k === "degree" && /master/.test(s)) out.push("master of science", "master of science ms", "masters degree", "masters", "master", "ms", "m s", "msc", "graduate degree", "graduate");
    if (k === "phone_type" && /mobile|cell/.test(s)) out.push("mobile", "cell", "cellular", "mobile phone", "cell phone", "personal mobile");
    if (k === "location" || k === "city") out.push(norm(String(v).split(",")[0]));
    if (k === "salary_type" && /annual/.test(s)) out.push("annual", "annually", "yearly", "year", "per year", "salary", "salaried", "annual salary");
    if (k === "school_type" && /graduate/.test(s)) out.push("graduate school", "graduate", "university", "college university", "college or university", "4 year college", "four year college", "college");
    if (k === "school_type" && /university/.test(s)) out.push("university", "college university", "college or university", "4 year college", "four year college", "college", "undergraduate");
    if (k === "month") { const i = MONTH_NAMES.findIndex((m) => norm(m) === s); if (i >= 0) out.push(MONTH_NAMES[i].slice(0, 3).toLowerCase(), String(i + 1), String(i + 1).padStart(2, "0")); }
    if (k === "phone_country_code" && /^1$/.test(s)) // "+1" picks the United States entry
      out.push("united states 1", "united states of america 1", "us 1", "usa 1", "1 united states", "1 united states of america", "1", "united states", "united states of america");
    if (k === "how_did_you_hear" && /website|career site|careers/.test(s)) {
      const co = norm(cfg.job.company || "").split(" ")[0];
      out.push("company website", "company career site", "company careers site", "career site", "careers site", "careers page", "corporate website",
        "employer website", "company web site", "website", "internet", ...(co ? [`${co} website`, `${co} careers`, `${co} career site`, `${co} com`] : []));
    }
    return [...new Set(out.filter(Boolean))];
  }
  const tokens = (s) => norm(s).split(" ").filter((w) => w.length > 1 && !["of", "and", "the", "in", "a", "an"].includes(w)).map((w) => w.replace(/s$/, ""));
  // options: [{el, text}] -> best option or null
  function chooseOption(options, k, value) {
    const opts = options.filter((o) => o.text && !GENERIC.test(clean(o.text)) && !/^(none|n a|-+)$/.test(norm(o.text)));
    if (k === "eeo_disability" || k === "eeo_hispanic" || k === "eeo_veteran") {
      // "No, I do not have a disability...", "No, not Hispanic or Latino", "I am not a protected veteran"
      const want = yesNo(value);
      if (want) {
        const neg = /^(no|not|i am not|i do not|i don t|i dont)\b/;
        const o = want === "no"
          ? opts.find((x) => neg.test(norm(x.text)) && !/wish|want|prefer|decline|answer|identify/.test(norm(x.text)))
          : opts.find((x) => /^(yes|i am a|i identify|i have)\b/.test(norm(x.text)));
        if (o) return o;
      }
    }
    if (YESNO.has(k) || typeof value === "boolean") {
      const want = yesNo(value);
      if (!want) return null;
      return opts.find((o) => norm(o.text) === want) || opts.find((o) => new RegExp(`^${want}\\b`).test(norm(o.text))) || null;
    }
    const al = aliases(k, value);
    let o = null;
    for (const a of al) if ((o = opts.find((x) => norm(x.text) === a))) return o; // closest alias first
    o = opts.find((x) => al.some((a) => a.length > 3 && norm(x.text).startsWith(a + " ")));
    if (o) return o;
    if (k === "location" || k === "city") {
      const city = norm(String(value).split(",")[0]);
      const st = (cfg.profile.state || "").toUpperCase();
      const stWords = [norm(st), norm(US_STATES[st] || "")].filter(Boolean);
      o = opts.find((x) => norm(x.text).startsWith(city) && (!stWords.length || stWords.some((w) => (" " + norm(x.text) + " ").includes(" " + w + " "))));
      if (o) return o;
    }
    // token overlap: every option word must come from the answer, and it must cover at least half of the answer
    const vt = new Set(tokens(value));
    let best = null, bestScore = 0;
    for (const x of opts) {
      const ot = tokens(x.text);
      if (!ot.length) continue;
      const common = ot.filter((w) => vt.has(w)).length;
      const score = common / ot.length + common / Math.max(vt.size, 1);
      if (common === ot.length && common / Math.max(vt.size, 1) >= 0.5 && score > bestScore) { best = x; bestScore = score; }
    }
    if (!best && k === "eeo_race" && opts.some((x) => /hispanic/i.test(x.text)) && yesNo(cfg.profile.eeo_hispanic) === "no") {
      // an "Ethnicity" list that only asks Hispanic or not (Cornerstone: Hispanic or Latino / Other / Decline)
      best = opts.find((x) => /\b(not|non) ?hispanic/.test(norm(x.text))) || opts.find((x) => norm(x.text) === "other") || null;
    }
    if (!best && k === "how_did_you_hear" && /website|career/.test(norm(value))) // "Fehr & Peers Website", "Our careers page"
      best = opts.find((x) => /website|career site|careers (page|site)|company site|our site/.test(norm(x.text)) && !/indeed|linkedin|glassdoor|zip ?recruiter|job board/.test(norm(x.text))) || null;
    return best;
  }

  // ---------- acting on the page ----------
  // Only dropdown openers, options, radios and labels may ever be clicked. Never a button that moves the form on.
  const CLICKABLE = "[role=option],[role=radio],[role=combobox],[aria-haspopup],[role=menuitem],[role=menuitemradio],label,select,[class*=__option],[class*=-option],[id*=-option-],[class*=__control],li," +
    "input:not([type=submit]):not([type=button]):not([type=image]):not([type=reset]):not([type=file]):not([type=checkbox])";
  function safeToClick(el) {
    if (!el || el.closest("#__coaf_panel")) return false;
    if (!el.matches(CLICKABLE) && !el.closest("[role=option],[role=listbox]")) return false;
    if (el.matches("input[type=submit],button[type=submit]")) return false;
    if (el.matches("button,a,input[type=button]") && !el.matches("[aria-haspopup],[role=combobox],[role=option],[role=radio],[role=menuitemradio]")) return false;
    return true;
  }
  function press(el) {
    if (!safeToClick(el)) throw new Error("refused to click " + el.tagName);
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, composed: true, view: window, button: 0, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
    el.dispatchEvent(new PointerEvent("pointerdown", o));
    el.dispatchEvent(new MouseEvent("mousedown", o));
    el.dispatchEvent(new PointerEvent("pointerup", o));
    el.dispatchEvent(new MouseEvent("mouseup", o));
    el.click();
  }
  const keyPress = (el, k, code = 0) => {
    for (const t of ["keydown", "keyup"]) el.dispatchEvent(new KeyboardEvent(t, { key: k, code: k, keyCode: code, which: code, bubbles: true, composed: true }));
  };
  function setValue(el, v) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
  }
  function working(el) {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.style.setProperty("outline", `3px solid ${AMBER}`, "important");
  }
  function mark(el, color, tip, bg) {
    el.dataset.coafFilled = "1";
    el.title = tip;
    el.style.setProperty("outline", `3px solid ${color}`, "important");
    el.style.setProperty("outline-offset", "1px", "important");
    if (bg) el.style.setProperty("background-color", bg, "important");
  }
  const unmark = (el) => el.style.removeProperty("outline");
  function record(label, k, value) {
    filled.push({ time: new Date().toTimeString().slice(0, 8), label: (label || k).slice(0, 60), key: k, value: String(value).slice(0, 80) });
    report();
  }

  async function typeText(el, val, speed = cfg.job.speed) {
    el.focus();
    el.dispatchEvent(new FocusEvent("focusin", { bubbles: true }));
    let cur = el.value || "";
    for (const ch of val) {
      if (!alive()) return;
      cur += ch;
      el.dispatchEvent(new KeyboardEvent("keydown", { key: ch, bubbles: true, composed: true }));
      setValue(el, cur);
      el.dispatchEvent(new InputEvent("input", { bubbles: true, composed: true, data: ch, inputType: "insertText" }));
      el.dispatchEvent(new KeyboardEvent("keyup", { key: ch, bubbles: true, composed: true }));
      if (speed) await sleep(speed);
    }
  }
  function phoneFor(el, v) {
    const digits = String(v).replace(/\D/g, "");
    const max = Number(el.getAttribute("maxlength")) || 0;
    let patternOk = true;
    try { patternOk = !el.pattern || new RegExp(`^(?:${el.pattern})$`).test(v); } catch { /* bad pattern attribute */ }
    return (max && max < String(v).length) || !patternOk ? digits : String(v);
  }
  async function fillText(el, info, k, v) {
    let val = String(v);
    if (k === "phone") val = phoneFor(el, val);
    if (YESNO.has(k)) {
      if (typeof v === "boolean") val = v ? "Yes" : "No";
      const detail = /\((.+)\)/.exec(val);
      if (detail && !/^(are|do|does|will|would|have|has|is|can|could)\b/i.test(info.label)) val = detail[1]; // "What type of visa...?"
    }
    working(el);
    await sleep(300);
    await typeText(el, val, val.length > 80 ? Math.min(cfg.job.speed || 0, 4) : cfg.job.speed); // long text: fast but visible
    if (!alive()) return;
    if (clean(el.value) !== clean(val)) { // masked/reformatting inputs: set the whole value at once
      setValue(el, val);
      el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    }
    el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    el.blur();
    el.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
    mark(el, GREEN, `autofill: ${k} (from profile.json)`, "#f0fdf4");
    record(info.label, k, val);
  }

  // ---------- dropdowns ----------
  function shownValue(el) {
    if (el.tagName === "INPUT") {
      if (el.value) return el.value;
      for (let n = el.parentElement, i = 0; n && i < 5; n = n.parentElement, i++) { // the widget's value display
        if (groupsIn(n) > 1) break;
        const sv = n.querySelector(VALUE_SEL + ",[class*=pill]");
        if (sv && clean(sv.innerText)) return clean(sv.innerText);
      }
      return "";
    }
    return clean(el.innerText || el.value || "");
  }
  const emptyChoice = (el) => { const v = stripReq(shownValue(el)); return !v || GENERIC.test(v) || /^(select|choose|please)\b/i.test(v); };
  function visibleOptions(el, rs) {
    const ids = [el.getAttribute("aria-controls"), el.getAttribute("aria-owns")].filter(Boolean).join(" ").split(/\s+/).filter(Boolean);
    let pool = [];
    for (const id of ids) { const lb = byId(el, id); if (lb) pool.push(...lb.querySelectorAll("[role=option]"), ...(lb.matches("[role=option]") ? [lb] : [])); }
    if (!pool.length) pool = deepAll("[role=option],[class*=select__option],[id*=-option-],.select2-results__option,[data-automation-id=promptOption]", rs);
    const seen = new Set();
    return pool.filter((o) => visible(o) && !o.closest("#__coaf_panel") && !o.matches("[aria-disabled=true]") && !seen.has(o) && seen.add(o))
      .map((o) => ({ el: o, text: clean(o.innerText || o.textContent) }))
      .filter((o) => o.text);
  }
  async function waitOptions(el, ms) {
    const end = Date.now() + ms;
    let opts = [];
    while (Date.now() < end) {
      opts = visibleOptions(el, roots());
      if (opts.length) { await sleep(150); return visibleOptions(el, roots()); } // let a filtered list settle
      await sleep(120);
    }
    return opts;
  }
  function closeDropdown(el) {
    keyPress(el, "Escape", 27);
    if (document.activeElement && document.activeElement !== document.body) keyPress(document.activeElement, "Escape", 27);
    el.blur();
  }
  const searchable = (el) => el.tagName === "INPUT" && !el.readOnly;
  function searchTerm(k, v) {
    if (k === "location" || k === "city") return String(v).split(",")[0];
    if (k === "phone_country_code") return "United States";
    if (k === "school") return String(v).replace(/\(.*?\)/g, "").trim(); // drop a "(short name)" in brackets
    if (k === "state") return US_STATES[String(v).toUpperCase()] || String(v);
    if (k === "degree" && /master/i.test(v)) return "Master";
    if (k === "degree" && /bachelor/i.test(v)) return "Bachelor";
    if (k === "discipline") return String(v).replace(/\(.*?\)/g, "").trim();
    return String(v);
  }
  // Opens a custom dropdown, picks the matching option, and checks it took. Returns the option text or null.
  async function pickFromDropdown(el, k, v) {
    working(el);
    await sleep(300);
    const box = el.tagName === "INPUT" && el.closest("[class*=__control],[class*=control]");
    const opener = box && safeToClick(box) ? box : el;
    if (el.tagName === "INPUT") el.focus();
    try { press(opener); } catch { unmark(el); return null; }
    let opts = await waitOptions(el, 1500);
    let pick = chooseOption(opts, k, v);
    if (!pick && searchable(el) && !YESNO.has(k)) { // type to search (react-select, Workday prompts, Oracle, location boxes)
      await typeText(el, searchTerm(k, v));
      await sleep(250);
      if (el.matches("[data-automation-id=searchBox]") || /search/i.test(el.placeholder || "")) keyPress(el, "Enter", 13);
      opts = await waitOptions(el, 2500);
      pick = chooseOption(opts, k, v);
    }
    if (!pick) {
      closeDropdown(el);
      if (searchable(el) && el.value) { setValue(el, ""); el.dispatchEvent(new Event("input", { bubbles: true })); }
      unmark(el);
      return null;
    }
    pick.el.scrollIntoView({ block: "nearest" });
    await sleep(200);
    try { press(pick.el); } catch { closeDropdown(el); unmark(el); return null; }
    await sleep(500);
    if (emptyChoice(el) && searchable(el)) { keyPress(el, "Enter", 13); await sleep(400); } // some lists only take Enter
    if (emptyChoice(el)) { closeDropdown(el); unmark(el); return null; }
    return pick.text;
  }

  // ---------- one pass over the page ----------
  function choiceKind(el) {
    if (el.tagName === "SELECT") return "select";
    if (el.type === "radio" || el.getAttribute("role") === "radio") return "radio";
    if (el.matches("button[aria-haspopup=listbox],[role=combobox]:not(input),[aria-haspopup=listbox]:not(input)")) return "dropdown";
    if (el.tagName === "INPUT" && (el.getAttribute("role") === "combobox" || el.getAttribute("aria-autocomplete") === "list" || el.matches("[data-automation-id=searchBox]"))) return "combo";
    return null;
  }

  async function fillPass() {
    const rs = roots();
    const radiosDone = new Set();
    const list = deepAll(CONTROL_SEL, rs);
    const ordinals = blockOrdinals(list);
    for (const el of list) {
      if (!alive() || userBusy()) return; // you're typing or clicking; try again in a moment
      if (done.has(el) || el.disabled || el.closest("#__coaf_panel") || el.closest("[aria-hidden=true]")) continue;
      if (el.type === "checkbox" && shown(el)) { // the only box ever ticked: "I currently work here" on a current job
        done.add(el);
        const info = describe(el);
        const b = classifyBlock(info);
        const e = b && b.key === "current" && (cfg.profile.work_history || [])[ordinals.get(el) || 0];
        if (e && e.current && !el.checked) {
          working(el.closest("label") || el);
          await sleep(300);
          el.click();
          mark(el.closest("label") || el, GREEN, "autofill: you currently work here (cv.md)");
          record(info.label, "current job", "ticked");
        }
        continue;
      }
      if (el.matches("[type=checkbox],[type=password],[type=search]:not([data-automation-id=searchBox]),[type=date],[type=month],[type=number],[type=range],[type=color]")) { done.add(el); continue; }
      if (el.type === "file") { await handleFile(el); continue; }
      const kind = choiceKind(el);
      if (kind === "radio") { if (shown(el)) await handleRadio(el, radiosDone); continue; }
      // text boxes must really be on screen; shown() (a visible wrapper) is only for styled-away radios/selects/files
      if (!(kind === "select" ? shown(el) : visible(el) && el.getBoundingClientRect().width > 2)) continue;
      if (el.tagName === "INPUT" && el.readOnly && !kind) { done.add(el); continue; }
      const info = describe(el);
      if (el.tagName === "TEXTAREA") { // essays: only a draft career-ops wrote for this job, never made up
        done.add(el);
        if (clean(el.value) || EEO_AREA.test(info.area)) continue;
        const b = classifyBlock(info);
        if (b && b.key === "description") { // a job's description box: that job's cv.md bullets
          const text = blockValue(b, ordinals.get(el), el, info, null);
          if (text) await fillText(el, info, "description", text);
          continue;
        }
        const s = !b && classify(info, false);
        if (s && s.key && (TEXTAREA_KEYS.has(s.key) || ANSWER_KEYS.has(s.key))) { // a short/Yes-No answer in a multi-line box (Pinpoint asks everything that way)
          const val = cfg.profile[s.key] ?? derived(s.key, el, info);
          if (val != null) { await fillText(el, info, s.key, val); continue; }
        }
        const d = !b && draftFor(info, true);
        if (d) await fillDraft(el, info, d);
        continue;
      }
      const c = classify(info, !!kind);
      if (c && c.flag) { flags.set(el, c.flag); done.add(el); continue; }
      let v = c ? (c.block ? blockValue(c, ordinals.get(el), el, info, kind) : cfg.profile[c.key]) : null;
      if (c && c.block && (c.key === "start" || c.key === "end") && kind) c.key = /^[A-Z]/.test(v || "") ? "month" : "year";
      if (c && c.key === "degree_type") c.key = "degree"; // match options the way a degree is matched
      // the posting's own top pay beats your default; otherwise data-derived answers (resume summary, today's date...)
      if (c && !c.block) v = (c.key === "salary_expectation" ? derived(c.key, el, info) : null) ?? v ?? derived(c.key, el, info);
      if (v == null && !kind && !clean(el.value) && (!c || (!c.block && ANSWER_KEYS.has(c.key))) && isQuestion(info.label)) {
        const d = draftFor(info, false); // a question text box with no profile answer: use the report's draft
        done.add(el);
        if (d) await fillDraft(el, info, d);
        continue;
      }
      if (!c) { done.add(el); continue; }
      if (v == null || (typeof v === "boolean" && !kind)) { done.add(el); continue; }
      if (kind === "select") { await handleSelect(el, info, c.key, v); continue; }
      if (kind === "dropdown" || kind === "combo") {
        if (!emptyChoice(el)) { done.add(el); continue; } // never overwrite a choice
        const n = (tries.get(el) || 0) + 1;
        tries.set(el, n);
        if (n >= 2) done.add(el);
        const picked = await pickFromDropdown(el, c.key, v);
        if (picked) {
          done.add(el);
          mark(el, GREEN, `autofill: ${c.key}`);
          record(info.label, c.key, picked);
        } else if (kind === "combo" && ["location", "city", "school"].includes(c.key) && !el.value && n >= 2) {
          await fillText(el, info, c.key, v); // free-text box with suggestions: keep the typed answer
        }
        continue;
      }
      done.add(el);
      if (clean(el.value)) continue; // never overwrite what's already there
      await fillText(el, info, c.key, v);
    }
  }

  async function handleSelect(el, info, k, v) {
    done.add(el);
    const cur = el.options[el.selectedIndex];
    if (el.selectedIndex > 0 && cur && !GENERIC.test(clean(cur.text))) return; // never overwrite a choice
    const pick = chooseOption([...el.options].filter((o) => !o.disabled).map((o) => ({ el: o, text: clean(o.text) })), k, v);
    if (!pick) return;
    working(el);
    await sleep(300);
    el.focus();
    el.value = pick.el.value;
    pick.el.selected = true;
    el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    el.blur();
    mark(el, GREEN, `autofill: ${k}`);
    record(info.label, k, pick.text);
  }

  function radioGroup(el) {
    if (el.type === "radio" && el.name) return [...el.getRootNode().querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`)];
    const g = el.closest("[role=radiogroup]");
    return g ? [...g.querySelectorAll("[role=radio]")] : [el];
  }
  function commonBox(els) {
    let n = parentOf(els[0]);
    while (n && n.nodeType === 1 && !els.every((e) => n.contains(e))) n = parentOf(n);
    return n && n.nodeType === 1 ? n : null;
  }
  function optionLabel(r) {
    if (r.getAttribute("role") === "radio") return clean(r.getAttribute("aria-label") || r.innerText);
    if (r.id) { const l = r.getRootNode().querySelector?.(`label[for="${CSS.escape(r.id)}"]`); if (l) return clean(l.innerText); }
    const l = r.closest("label");
    if (l) return clean(l.innerText);
    if (r.getAttribute("aria-label")) return clean(r.getAttribute("aria-label"));
    const p = r.parentElement;
    if (p && p.querySelectorAll("input[type=radio]").length === 1 && clean(p.innerText)) return clean(p.innerText);
    return clean(r.nextSibling?.textContent || r.value);
  }
  function groupQuestion(group) {
    const first = group[0];
    const opts = group.map(optionLabel).filter(Boolean);
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const minusOptions = (t) => { for (const o of opts) t = t.replace(new RegExp(`(^|\\s)${esc(o)}(?=\\s|$)`, "i"), " "); return stripReq(t); };
    // screen-reader-only labels are hidden on purpose, so fall back to their raw text
    const idsText = (el, ids) => (ids || "").split(/\s+/).filter(Boolean).map((i) => byId(el, i)).filter(Boolean).map((n) => textOf(n) || n.textContent || "").join(" ");
    // Pinpoint and others point each radio at its question with aria-labelledby/-describedby
    for (const a of ["aria-labelledby", "aria-describedby"]) {
      const t = minusOptions(idsText(first, first.getAttribute(a)));
      if (t && !GENERIC.test(t)) return t;
    }
    const g = first.closest("[role=radiogroup]");
    if (g) {
      const t = minusOptions(idsText(g, g.getAttribute("aria-labelledby")) || g.getAttribute("aria-label") || "");
      if (t) return t;
    }
    const fs = first.closest("fieldset");
    if (fs && groupsIn(fs) <= 1) { const lg = fs.querySelector("legend"); if (lg && textOf(lg)) return stripReq(textOf(lg)); } // not a "3. Questions" section
    // Walk out from the options until there is text besides the option labels (Lever, Taleo)
    for (let n = commonBox(group), i = 0; n && n.nodeType === 1 && n !== document.body && i < 5; n = parentOf(n), i++) {
      if (i && groupsIn(n) > 1) break;
      const t = minusOptions(textOf(n));
      if (t && !GENERIC.test(t) && t.length < 300) return t;
    }
    return "";
  }
  async function handleRadio(el, radiosDone) {
    const group = radioGroup(el);
    const gid = group[0];
    if (radiosDone.has(gid)) return;
    radiosDone.add(gid);
    group.forEach((r) => done.add(r));
    if (group.some((r) => r.checked || r.getAttribute("aria-checked") === "true")) return;
    const label = groupQuestion(group);
    const info = { label, text: norm(label), attrs: splitAttr(gid.name || ""), area: sectionOf(gid), required: group.some((r) => r.required), ac: "" };
    infoCache.set(gid, info);
    const c = classify(info, true);
    if (!c) return;
    if (c.flag) { flags.set(gid, c.flag); return; }
    const v = cfg.profile[c.key];
    if (v == null) return;
    const pick = chooseOption(group.map((r) => ({ el: r, text: optionLabel(r) })), c.key, v);
    if (!pick) return;
    const target = pick.el.getAttribute("role") === "radio" || visible(pick.el) ? pick.el
      : (pick.el.id && pick.el.getRootNode().querySelector?.(`label[for="${CSS.escape(pick.el.id)}"]`)) || pick.el.closest("label") || pick.el;
    working(target);
    await sleep(300);
    try { press(target); } catch { unmark(target); return; }
    if (pick.el.type === "radio" && !pick.el.checked) { pick.el.checked = true; pick.el.dispatchEvent(new Event("change", { bubbles: true })); }
    unmark(target);
    group.forEach((r) => { r.dataset.coafFilled = "1"; });
    mark(commonBox(group) || target, GREEN, `autofill: ${c.key}`);
    record(label, c.key, pick.text);
  }

  // Which document a file input wants: from its label/attributes, else from the nearby text.
  function fileKind(el) {
    const pick = (s) => (/cover/.test(s) ? "cover" : /resume|résumé|\bcv\b|curriculum/.test(s) ? "resume" : null);
    let kind = pick((labelFor(el) + " " + splitAttr([el.name, el.id, el.getAttribute("data-automation-id")].join(" "))).toLowerCase());
    for (let n = parentOf(el), i = 0; !kind && n && n.nodeType === 1 && i < 5; n = parentOf(n), i++) {
      const text = textOf(n).toLowerCase();
      if (text.length > 400) break;
      kind = pick(text);
    }
    return kind;
  }
  async function handleFile(el) {
    if (done.has(el) || !shown(el)) return; // e.g. an upload box inside a closed dialog
    done.add(el);
    const kind = fileKind(el);
    if (!kind || !cfg.job.n || uploaded.has(kind) || (el.files && el.files.length)) return;
    const doc = await send({ type: "file", kind });
    if (!doc || !alive()) return;
    uploaded.add(kind);
    const bytes = Uint8Array.from(atob(doc.b64), (c) => c.charCodeAt(0));
    const dt = new DataTransfer();
    dt.items.add(new File([bytes], doc.name, { type: doc.type }));
    let box = el;
    for (let n = el, i = 0; n && n.nodeType === 1 && i < 4; n = parentOf(n), i++) if (visible(n) && n.getBoundingClientRect().width > 1) { box = n; break; }
    box.scrollIntoView({ block: "center", behavior: "smooth" });
    await sleep(300);
    el.files = dt.files;
    el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    mark(box, BLUE, `autofill: uploaded ${doc.name}`);
    el.dataset.coafFilled = "1";
    record(kind === "cover" ? "Cover letter" : "Resume", `${kind} file`, doc.name);
  }

  // ---------- what still needs you ----------
  function needsYou() {
    const out = [], seen = new Set();
    for (const e of deepAll(CONTROL_SEL)) {
      if (e.disabled || e.dataset.coafFilled || e.closest("#__coaf_panel") || e.closest("[aria-hidden=true]")) continue;
      if (e.matches("[type=checkbox],[type=password],[type=search]:not([data-automation-id=searchBox])")) continue;
      const kind = choiceKind(e);
      let empty, label, flagged;
      if (kind === "radio") {
        const group = radioGroup(e);
        if (seen.has(group[0])) continue;
        seen.add(group[0]);
        if (!group.some(shown) || group.some((r) => r.dataset.coafFilled)) continue;
        empty = !group.some((r) => r.checked || r.getAttribute("aria-checked") === "true");
        label = (infoCache.get(group[0]) || {}).label || groupQuestion(group);
        flagged = flags.get(group[0]);
      } else if (e.type === "file") {
        if (!shown(e)) continue;
        const fk = fileKind(e);
        if ((e.files && e.files.length) || (fk && uploaded.has(fk))) continue;
        empty = true;
        label = labelFor(e);
        if (!label || /^(attach|upload)/i.test(label)) label = fk === "cover" ? "Cover letter upload" : fk === "resume" ? "Resume upload" : "File upload";
      } else {
        if (!(kind === "select" ? shown(e) : visible(e) && e.getBoundingClientRect().width > 2)) continue;
        if (/captcha/i.test((e.name || "") + (e.id || ""))) continue;
        if (kind === "combo" && !e.id && !e.getAttribute("aria-labelledby") && e.closest("[class*=container],[class*=control]")) continue; // a widget's inner box
        empty = e.tagName === "SELECT" ? e.selectedIndex <= 0 || GENERIC.test(clean(e.options[e.selectedIndex]?.text)) : kind ? emptyChoice(e) : !clean(e.value);
        if (!empty) continue;
        label = describe(e).label;
        flagged = flags.get(e);
      }
      if (!empty || !clean(label)) continue; // unlabeled leftovers are widget internals, not questions
      if (cfg.profile.middle_name === "" && /\bmiddle (name|initial)/i.test(label)) continue; // you have none: nothing to do
      const info = infoCache.get(e);
      const required = (info && info.required) || e.required || e.getAttribute("aria-required") === "true";
      out.push({ label: clean(label || e.name || "(unlabeled)").slice(0, 80) + (flagged ? ` (${flagged})` : ""), required: !!(required || flagged) });
    }
    return out;
  }

  function report() {
    if (alive()) send({ type: "report", filled, needs: needsYou() });
  }

  function drawPanel(data) {
    let p = document.getElementById("__coaf_panel");
    if (!p) {
      p = document.createElement("div");
      p.id = "__coaf_panel";
      p.style.cssText =
        "position:fixed;right:12px;bottom:12px;z-index:2147483647;width:340px;max-height:45vh;overflow:auto;" +
        "background:#0f172a;color:#e2e8f0;font:12px/1.4 Segoe UI,Arial,sans-serif;border-radius:10px;" +
        "box-shadow:0 8px 24px rgba(0,0,0,.35);padding:0 0 8px;opacity:.96;text-align:left";
      document.documentElement.appendChild(p);
    }
    const collapsed = p.dataset.collapsed === "1";
    p.replaceChildren();
    const head = document.createElement("div");
    head.style.cssText = "position:sticky;top:0;background:#1e293b;padding:8px 10px;font-weight:600;border-radius:10px 10px 0 0;display:flex;gap:8px;align-items:center";
    const title = document.createElement("span");
    title.style.cssText = "flex:1;cursor:pointer";
    title.textContent = `Autofill: ${data.filled.length} filled, ${data.needs.length} need you ` + (collapsed ? "[+]" : "[-]");
    title.onclick = () => { p.dataset.collapsed = collapsed ? "0" : "1"; drawPanel(data); };
    const stop = document.createElement("button");
    stop.textContent = "Stop";
    stop.style.cssText = "background:#334155;color:#e2e8f0;border:0;border-radius:6px;padding:2px 8px;cursor:pointer;font:inherit";
    stop.onclick = () => send({ type: "stop" });
    head.append(title, stop);
    p.appendChild(head);
    if (collapsed) return;
    const line = (text, css) => { const d = document.createElement("div"); d.style.cssText = css; d.textContent = text; p.appendChild(d); return d; };
    const job = data.job || {};
    line(job.n ? `#${job.n} ${job.company}: ${job.role}` : "Profile only (no resume/cover attached)", "padding:6px 10px 0;color:#94a3b8");
    const section = (name, color, rows) => {
      line(name, `padding:6px 10px 2px;color:${color};font-weight:600`);
      for (const [a, b, c] of rows) {
        const r = line("", "padding:1px 10px 1px 18px");
        const s = document.createElement("span");
        s.style.color = c || "#94a3b8";
        s.textContent = a;
        r.append(s, document.createTextNode(b ? "  " + b : ""));
      }
      if (!rows.length) line("(none)", "padding:1px 18px;color:#64748b");
    };
    section("Filled by autofill", "#4ade80", data.filled.filter((f) => !f.draft).map((f) => [f.label + ":", f.value]));
    const drafts = data.filled.filter((f) => f.draft);
    if (drafts.length) section("Drafted answers: read and edit these (purple)", "#c084fc", drafts.map((f) => [(f.check ? "* check: " : "") + f.label + ":", f.value + "…", f.check ? "#fca5a5" : "#e9d5ff"]));
    section("Needs you", "#fbbf24", data.needs.map((n) => [(n.required ? "* " : "") + n.label, "", n.required ? "#fca5a5" : "#cbd5e1"]));
    line("Nothing is submitted automatically. Click Next yourself; each new page is filled as it appears. Review, then submit.", "padding:6px 10px 0;color:#64748b");
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "panel" && TOP && alive()) drawPanel(msg.data);
    if (msg.type === "stop") {
      stopped = true;
      document.getElementById("__coaf_panel")?.remove();
    }
    if (msg.type === "start" && stopped) { // restarted from the popup on the same page
      stopped = false;
      run();
    }
  });

  async function run() {
    cfg = await send({ type: "config" });
    if (!cfg) return; // tab is not armed
    cfg.extra = await send({ type: "answers" }); // drafts, cover letter text, top of the posted pay range
    while (alive()) {
      try {
        await fillPass();
        report();
      } catch {
        // the page changed under us mid-pass; the next pass picks it up
      }
      await sleep(1500);
    }
  }
  run();
})();

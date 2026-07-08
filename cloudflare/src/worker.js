/**
 * Static dashboard + on-demand scan trigger via GitHub Actions workflow_dispatch.
 *
 * Worker secret GITHUB_PAT (synced from GitHub repo secret DASHBOARD_GITHUB_PAT):
 *   Classic PAT recommended for private repo — scopes: repo + workflow
 *   Fine-grained also works if org approved + Actions (R/W) + Contents (Read)
 */

const WORKFLOWS = {
  hk: "280047321",
  us: "283958997",
};
const ON_DEMAND_WORKFLOW = "289018494";
const ON_DEMAND_RUN_NAMES = {
  hk: "scan_hk",
  us: "scan_us",
};
const WORKFLOW_LABELS = {
  hk: "cloudflare-auto.yml",
  us: "cloudflare-auto-us.yml",
};

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };
const GITHUB_API = "2022-11-28";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: JSON_HEADERS });
}

function cors(request) {
  const origin = request.headers.get("Origin");
  if (!origin) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Refresh-Key",
  };
}

function withCors(response, request) {
  const extra = cors(request);
  const headers = new Headers(response.headers);
  for (const [k, v] of Object.entries(extra)) headers.set(k, v);
  return new Response(response.body, { status: response.status, headers });
}

function parseMarket(url) {
  const m = String(url.searchParams.get("market") || "hk").toLowerCase();
  return m === "us" ? "us" : "hk";
}

function workflowId(market) {
  return WORKFLOWS[market] || WORKFLOWS.hk;
}

function workflowLabel(market) {
  return WORKFLOW_LABELS[market] || WORKFLOW_LABELS.hk;
}

function cooldownMs(env) {
  const n = parseInt(String(env.REFRESH_COOLDOWN_MIN || "10"), 10);
  return (Number.isFinite(n) && n > 0 ? n : 10) * 60 * 1000;
}

function authOk(request, env) {
  const secret = String(env.REFRESH_SECRET || "").trim();
  if (!secret) return true;
  const key = String(request.headers.get("X-Refresh-Key") || "").trim();
  return key === secret;
}

function tokenMissing(env) {
  return !String(env.GITHUB_PAT || "").trim();
}

function githubAuthError(status, text) {
  if (status === 401) {
    return "GitHub token rejected — update DASHBOARD_GITHUB_PAT (classic PAT: repo + workflow scopes)";
  }
  if (status === 403) {
    return "GitHub token forbidden — for private repo use classic PAT (repo + workflow) or get org to approve fine-grained token";
  }
  if (status === 404) {
    return (
      "GitHub 404 — token cannot see private repo numstation/hkstockdashboard. " +
      "Create NEW classic token (ghp_…) at github.com/settings/tokens/new with BOTH repo + workflow checked. " +
      "If you see numstation → click Authorize SSO. Update secret DASHBOARD_GITHUB_PAT, then Run Cloudflare auto update."
    );
  }
  return `GitHub API ${status}: ${text.slice(0, 180)}`;
}

async function githubFetch(env, path, init = {}) {
  const token = String(env.GITHUB_PAT || "").trim();
  if (!token) {
    throw new Error("GITHUB_PAT not configured on Worker");
  }
  const repo = String(env.GITHUB_REPO || "numstation/hkstockdashboard").trim();
  const url = `https://api.github.com/repos/${repo}${path}`;
  return fetch(url, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": GITHUB_API,
      "User-Agent": "hkstockdashboard-refresh/1.0",
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
  });
}

async function cacheCooldownHit(env, market, cooldown) {
  const cache = caches.default;
  const key = new Request(`https://scan-cooldown.local/${market}`, { method: "GET" });
  const hit = await cache.match(key);
  if (!hit) return null;
  const ts = parseInt(await hit.text(), 10);
  if (!Number.isFinite(ts)) return null;
  const age = Date.now() - ts;
  if (age < cooldown) {
    return Math.ceil((cooldown - age) / 60000);
  }
  return null;
}

async function markCooldown(env, market) {
  const cache = caches.default;
  const key = new Request(`https://scan-cooldown.local/${market}`, { method: "GET" });
  await cache.put(
    key,
    new Response(String(Date.now()), {
      headers: { "Cache-Control": `max-age=${Math.ceil(cooldownMs(env) / 1000)}` },
    }),
  );
}

async function latestWorkflowRun(env, market) {
  const scheduledId = workflowId(market);
  const onDemandName = ON_DEMAND_RUN_NAMES[market] || ON_DEMAND_RUN_NAMES.hk;

  const [scheduledRes, onDemandRes] = await Promise.all([
    githubFetch(env, `/actions/workflows/${scheduledId}/runs?per_page=1`),
    githubFetch(env, `/actions/workflows/${ON_DEMAND_WORKFLOW}/runs?per_page=15`),
  ]);

  if (!scheduledRes.ok && !onDemandRes.ok) {
    const errRes = scheduledRes.ok ? onDemandRes : scheduledRes;
    return { run: null, apiError: githubAuthError(errRes.status, await errRes.text()) };
  }

  const candidates = [];

  if (scheduledRes.ok) {
    const scheduledData = await scheduledRes.json();
    const scheduledRun = Array.isArray(scheduledData.workflow_runs)
      ? scheduledData.workflow_runs[0]
      : null;
    if (scheduledRun) candidates.push(scheduledRun);
  }

  if (onDemandRes.ok) {
    const onDemandData = await onDemandRes.json();
    for (const run of onDemandData.workflow_runs || []) {
      const name = String(run.name || "").toLowerCase();
      const title = String(run.display_title || "").toLowerCase();
      if (name === onDemandName || title === onDemandName) {
        candidates.push(run);
      }
    }
  }

  candidates.sort(
    (a, b) => Date.parse(b.created_at || "") - Date.parse(a.created_at || ""),
  );
  return { run: candidates[0] || null, apiError: null };
}

function runSummary(run) {
  if (!run) return null;
  return {
    id: run.id,
    status: run.status,
    conclusion: run.conclusion,
    created_at: run.created_at,
    updated_at: run.updated_at,
    html_url: run.html_url,
    event: run.event,
  };
}

function runBlocksNewTrigger(run, cooldown) {
  if (!run) return { blocked: false };
  const created = Date.parse(run.created_at || "");
  if (!Number.isFinite(created)) return { blocked: false };

  const age = Date.now() - created;
  const st = String(run.status || "").toLowerCase();
  if (st === "queued" || st === "in_progress" || st === "waiting" || st === "pending") {
    return {
      blocked: true,
      code: 409,
      error: "scan_already_running",
      message: "掃描已在進行中，請稍候再試。",
      run: runSummary(run),
    };
  }
  if (age < cooldown) {
    const waitMin = Math.ceil((cooldown - age) / 60000);
    return {
      blocked: true,
      code: 429,
      error: "cooldown",
      message: `請 ${waitMin} 分鐘後再觸發（避免 Yahoo 限流）。`,
      run: runSummary(run),
      retry_after_min: waitMin,
    };
  }
  return { blocked: false };
}

async function dispatchWorkflow(env, market) {
  const eventType = market === "us" ? "scan_us" : "scan_hk";
  const res = await githubFetch(env, `/dispatches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      event_type: eventType,
      client_payload: { market },
    }),
  });
  if (res.status === 204) return { ok: true };
  const text = await res.text();
  throw new Error(githubAuthError(res.status, text));
}

async function handleStockAnalyze(request, env) {
  const base = String(env.ANALYSIS_API_URL || "").trim().replace(/\/$/, "");
  if (!base) {
    return json(
      {
        ok: false,
        error: "analysis_api_not_configured",
        message:
          "Set Worker secret ANALYSIS_API_URL to your Railway analysis API (e.g. https://xxx.up.railway.app).",
      },
      503,
    );
  }
  let code = "";
  try {
    if (request.method === "GET") {
      const u = new URL(request.url);
      code = String(u.searchParams.get("code") || u.searchParams.get("stock_code") || "").trim();
    } else {
      const body = await request.json();
      code = String(body?.stock_code || body?.code || "").trim();
    }
  } catch (_) {
    code = "";
  }
  if (!code) {
    return json({ ok: false, error: "missing_code", message: "Provide stock_code or code." }, 400);
  }
  const target = `${base}/api/v1/stock/analyze`;
  const res = await fetch(target, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stock_code: code }),
  });
  const text = await res.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch (_) {
    return json(
      { ok: false, error: "upstream_invalid_json", message: text.slice(0, 200) },
      502,
    );
  }
  return json(payload, res.status);
}

async function handleApi(request, env, url) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors(request) });
  }

  if (tokenMissing(env)) {
    return withCors(
      json({ ok: false, error: "GITHUB_PAT not configured on Worker" }, 502),
      request,
    );
  }

  const market = parseMarket(url);

  if (url.pathname === "/api/refresh/status" && request.method === "GET") {
    try {
      const { run, apiError } = await latestWorkflowRun(env, market);
      return withCors(
        json({
          ok: !apiError,
          market,
          workflow: workflowLabel(market),
          run: runSummary(run),
          warning: apiError,
        }),
        request,
      );
    } catch (err) {
      return withCors(
        json({ ok: false, error: String(err.message || err) }, 502),
        request,
      );
    }
  }

  if (url.pathname === "/api/refresh" && request.method === "POST") {
    if (!authOk(request, env)) {
      return withCors(
        json({ ok: false, error: "unauthorized", message: "Invalid refresh key." }, 401),
        request,
      );
    }
    try {
      let bodyMarket = market;
      try {
        const body = await request.json();
        if (body && body.market === "us") bodyMarket = "us";
        if (body && body.market === "hk") bodyMarket = "hk";
      } catch (_) {
        /* empty body ok */
      }

      const cooldown = cooldownMs(env);
      const cacheWait = await cacheCooldownHit(env, bodyMarket, cooldown);
      if (cacheWait != null) {
        return withCors(
          json(
            {
              ok: false,
              error: "cooldown",
              message: `請 ${cacheWait} 分鐘後再觸發（避免 Yahoo 限流）。`,
              retry_after_min: cacheWait,
            },
            429,
          ),
          request,
        );
      }

      const { run, apiError } = await latestWorkflowRun(env, bodyMarket);
      if (!apiError && run) {
        const gate = runBlocksNewTrigger(run, cooldown);
        if (gate.blocked) {
          return withCors(
            json(
              {
                ok: false,
                error: gate.error,
                message: gate.message,
                run: gate.run,
                retry_after_min: gate.retry_after_min,
              },
              gate.code || 429,
            ),
            request,
          );
        }
      }

      await dispatchWorkflow(env, bodyMarket);
      await markCooldown(env, bodyMarket);
      return withCors(
        json({
          ok: true,
          market: bodyMarket,
          message: "掃描已排隊，約 5 分鐘後按 Reload 或等待自動更新。",
          previous_run: runSummary(run),
          warning: apiError || undefined,
        }),
        request,
      );
    } catch (err) {
      return withCors(
        json({ ok: false, error: "dispatch_failed", message: String(err.message || err) }, 502),
        request,
      );
    }
  }

  return withCors(json({ ok: false, error: "not_found" }, 404), request);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/stock/analyze") {
      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: cors(request) });
      }
      if (request.method === "GET" || request.method === "POST") {
        try {
          return withCors(await handleStockAnalyze(request, env), request);
        } catch (err) {
          return withCors(
            json({ ok: false, error: "analysis_proxy_failed", message: String(err.message || err) }, 502),
            request,
          );
        }
      }
      return withCors(json({ ok: false, error: "method_not_allowed" }, 405), request);
    }
    if (url.pathname.startsWith("/api/")) {
      return handleApi(request, env, url);
    }
    return env.ASSETS.fetch(request);
  },
};

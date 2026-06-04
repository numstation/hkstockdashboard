/**
 * Static dashboard + on-demand scan trigger via GitHub Actions workflow_dispatch.
 *
 * Secrets (wrangler secret put):
 *   GITHUB_PAT — fine-grained token with Actions: Read and write on this repo
 * Optional:
 *   REFRESH_SECRET — if set, client must send matching X-Refresh-Key header
 *
 * Vars (wrangler.toml [vars]):
 *   GITHUB_REPO, REFRESH_COOLDOWN_MIN
 */

const WORKFLOWS = {
  // Numeric IDs are stable; filename alone can 404 with fine-grained PATs.
  hk: "280047321",
  us: "283958997",
};
const WORKFLOW_LABELS = {
  hk: "cloudflare-auto.yml",
  us: "cloudflare-auto-us.yml",
};

const JSON_HEADERS = { "Content-Type": "application/json; charset=utf-8" };

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

async function githubFetch(env, path, init = {}) {
  const token = String(env.GITHUB_PAT || "").trim();
  if (!token) {
    throw new Error("GITHUB_PAT not configured on Worker");
  }
  const repo = String(env.GITHUB_REPO || "numstation/hkstockdashboard").trim();
  const url = `https://api.github.com/repos/${repo}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      "User-Agent": "hkstockdashboard-refresh/1.0",
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
  });
  return res;
}

async function latestWorkflowRun(env, market) {
  const wf = workflowId(market);
  const res = await githubFetch(
    env,
    `/actions/workflows/${wf}/runs?per_page=1`,
  );
  if (!res.ok) {
    const text = await res.text();
    if (res.status === 401) {
      throw new Error("GitHub token rejected — regenerate DASHBOARD_GITHUB_PAT");
    }
    if (res.status === 404) {
      throw new Error(
        "GitHub token cannot access Actions on this repo — add Contents: Read + Actions: Read and write on DASHBOARD_GITHUB_PAT",
      );
    }
    throw new Error(`GitHub runs API ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  const run = Array.isArray(data.workflow_runs) ? data.workflow_runs[0] : null;
  return run || null;
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
  const wf = workflowId(market);
  const res = await githubFetch(env, `/actions/workflows/${wf}/dispatches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main" }),
  });
  if (res.status === 204) return { ok: true };
  const text = await res.text();
  throw new Error(`GitHub dispatch ${res.status}: ${text.slice(0, 300)}`);
}

async function handleApi(request, env, url) {
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: cors(request) });
  }

  const market = parseMarket(url);

  if (url.pathname === "/api/refresh/status" && request.method === "GET") {
    try {
      const run = await latestWorkflowRun(env, market);
      return withCors(
        json({
          ok: true,
          market,
          workflow: workflowLabel(market),
          run: runSummary(run),
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

      const run = await latestWorkflowRun(env, bodyMarket);
      const gate = runBlocksNewTrigger(run, cooldownMs(env));
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

      await dispatchWorkflow(env, bodyMarket);
      return withCors(
        json({
          ok: true,
          market: bodyMarket,
          message: "掃描已排隊，約 5 分鐘後按 Reload 或等待自動更新。",
          previous_run: runSummary(run),
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
    if (url.pathname.startsWith("/api/")) {
      return handleApi(request, env, url);
    }
    return env.ASSETS.fetch(request);
  },
};

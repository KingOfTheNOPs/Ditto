function(task, responses) {
    const status = String(task.status || "").toLowerCase();
    if (status.includes("error")) {
        return { plaintext: responses.reduce((prev, cur) => prev + cur, "") };
    }

    if (responses.length === 0) {
        return { plaintext: "No response yet from agent..." };
    }

    const combined = responses.reduce((prev, cur) => prev + cur, "").trim();
    if (!combined) {
        return { plaintext: "" };
    }

    const safeString = (value) => value === undefined || value === null ? "" : String(value);
    const visitDate = (value) => {
        const number = Number(value);
        if (!Number.isFinite(number) || number <= 0) {
            return "";
        }
        const millis = number < 1000000000000 ? number * 1000 : number;
        const date = new Date(millis);
        return Number.isNaN(date.getTime()) ? "" : date.toISOString();
    };
    const urlParts = (value) => {
        const text = safeString(value);
        try {
            const parsed = new URL(text);
            return {
                scheme: parsed.protocol.replace(/:$/, ""),
                host: parsed.host || "(no host)",
                path: `${parsed.pathname || "/"}${parsed.search || ""}${parsed.hash || ""}`
            };
        } catch (_) {
            return {
                scheme: "",
                host: "(invalid url)",
                path: text
            };
        }
    };
    const exportString = (title, value) => ({
        name: title,
        type: "string",
        value: JSON.stringify(value, null, 2),
        title,
        startIcon: "download",
        hoverText: "Open formatted JSON for copy/save"
    });
    const viewDictionary = (title, value) => ({
        name: title,
        type: "dictionary",
        value,
        leftColumnTitle: "Field",
        rightColumnTitle: "Value",
        title
    });

    try {
        const parsed = JSON.parse(combined);
        if (parsed && parsed.ok === false) {
            return { plaintext: safeString(parsed.e || parsed.error || combined) };
        }

        const body = parsed && parsed.r && typeof parsed.r === "object" ? parsed.r : parsed;
        const results = Array.isArray(body) ? body : (Array.isArray(body.results) ? body.results : []);
        const query = safeString((body && body.query) || task.display_params || "");
        if (results.length === 0) {
            return { plaintext: combined };
        }

        const normalized = results.map((item) => {
            const parts = urlParts(item.url);
            return {
                ...item,
                host: parts.host,
                path: parts.path,
                scheme: parts.scheme,
                visitCountNumber: Number(item.visitCount || 0),
                typedCountNumber: Number(item.typedCount || 0),
                lastVisitIso: visitDate(item.lastVisitTime)
            };
        });

        const byHost = normalized.reduce((acc, item) => {
            const key = item.host || "(no host)";
            if (!acc[key]) {
                acc[key] = [];
            }
            acc[key].push(item);
            return acc;
        }, {});

        const hostRows = Object.keys(byHost).sort().map((host) => {
            const hostItems = byHost[host];
            const totalVisits = hostItems.reduce((sum, item) => sum + item.visitCountNumber, 0);
            const typedVisits = hostItems.reduce((sum, item) => sum + item.typedCountNumber, 0);
            const latest = hostItems
                .map((item) => Number(item.lastVisitTime || 0))
                .filter((value) => Number.isFinite(value))
                .sort((a, b) => b - a)[0];
            const summary = {
                host,
                resultCount: hostItems.length,
                totalVisits,
                typedVisits,
                latestVisit: visitDate(latest)
            };
            return {
                rowStyle: typedVisits > 0 ? { backgroundColor: "rgba(76, 175, 80, 0.12)" } : {},
                actions: {
                    plaintext: "",
                    button: {
                        name: "Actions",
                        type: "menu",
                        startIcon: "list",
                        value: [
                            viewDictionary(`Host summary: ${host}`, summary),
                            exportString(`Export host JSON: ${host}`, {
                                ...summary,
                                results: hostItems
                            }),
                            {
                                name: "Search Host",
                                type: "task",
                                startIcon: "search",
                                ui_feature: "browser_history:search",
                                parameters: { text: host }
                            }
                        ]
                    }
                },
                host: { plaintext: host, copyIcon: true },
                results: { plaintext: String(hostItems.length) },
                visits: { plaintext: String(totalVisits) },
                typed: { plaintext: String(typedVisits) },
                latest: { plaintext: summary.latestVisit }
            };
        });

        const rows = normalized
            .slice()
            .sort((a, b) => Number(b.lastVisitTime || 0) - Number(a.lastVisitTime || 0))
            .map((item) => {
                const title = safeString(item.title) || "(no title)";
                const url = safeString(item.url);
                const details = {
                    id: safeString(item.id),
                    title,
                    url,
                    scheme: item.scheme,
                    host: item.host,
                    path: item.path,
                    visitCount: item.visitCountNumber,
                    typedCount: item.typedCountNumber,
                    lastVisit: item.lastVisitIso
                };
                return {
                    rowStyle: item.typedCountNumber > 0
                        ? { backgroundColor: "rgba(76, 175, 80, 0.10)" }
                        : (item.visitCountNumber >= 10 ? { backgroundColor: "rgba(255, 193, 7, 0.14)" } : {}),
                    actions: {
                        plaintext: "",
                        button: {
                            name: "Actions",
                            type: "menu",
                            startIcon: "list",
                            value: [
                                viewDictionary(`History details: ${title}`, details),
                                exportString(`Export history JSON: ${title}`, details),
                                {
                                    name: "URL",
                                    type: "string",
                                    value: url,
                                    title: `URL: ${title}`,
                                    startIcon: "list",
                                    hoverText: "Open URL for copy/save"
                                },
                                {
                                    name: "Search Host",
                                    type: "task",
                                    startIcon: "search",
                                    ui_feature: "browser_history:search",
                                    parameters: { text: item.host }
                                }
                            ]
                        }
                    },
                    title: { plaintext: title, copyIcon: true },
                    host: { plaintext: item.host, copyIcon: true },
                    path: {
                        plaintext: safeString(item.path),
                        plaintextHoverText: url,
                        copyIcon: true
                    },
                    visits: { plaintext: String(item.visitCountNumber) },
                    typed: { plaintext: String(item.typedCountNumber) },
                    last_visit: { plaintext: item.lastVisitIso },
                    id: { plaintext: safeString(item.id), copyIcon: true }
                };
            });

        return {
            plaintext: `History results: ${results.length}${query ? ` for "${query}"` : ""}`,
            table: [
                {
                    headers: [
                        { plaintext: "actions", type: "button", width: 105, disableSort: true },
                        { plaintext: "host", type: "string", fillWidth: true },
                        { plaintext: "results", type: "number", width: 95 },
                        { plaintext: "visits", type: "number", width: 90 },
                        { plaintext: "typed", type: "number", width: 80 },
                        { plaintext: "latest", type: "date", width: 230 }
                    ],
                    rows: hostRows,
                    title: `History hosts (${hostRows.length})`
                },
                {
                    headers: [
                        { plaintext: "actions", type: "button", width: 105, disableSort: true },
                        { plaintext: "title", type: "string", fillWidth: true },
                        { plaintext: "host", type: "string", width: 220 },
                        { plaintext: "path", type: "string", fillWidth: true },
                        { plaintext: "visits", type: "number", width: 85 },
                        { plaintext: "typed", type: "number", width: 80 },
                        { plaintext: "last_visit", type: "date", width: 230 },
                        { plaintext: "id", type: "string", width: 95 }
                    ],
                    rows,
                    title: `History results (${rows.length})`
                }
            ]
        };
    } catch (error) {
        return { plaintext: combined };
    }
}

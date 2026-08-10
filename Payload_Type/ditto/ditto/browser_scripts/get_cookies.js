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

    const parseResponse = (text) => {
        const parsed = JSON.parse(text);
        if (Array.isArray(parsed)) {
            return { cookieCount: parsed.length, cookies: parsed };
        }
        return {
            cookieCount: Number(parsed.cookieCount ?? (Array.isArray(parsed.cookies) ? parsed.cookies.length : 0)),
            cookies: Array.isArray(parsed.cookies) ? parsed.cookies : []
        };
    };

    const safeString = (value) => value === undefined || value === null ? "" : String(value);
    const cookieLabel = (cookie) => `${safeString(cookie.domain)}${safeString(cookie.path)} ${safeString(cookie.name)}`.trim();
    const cookieHeader = (cookie) => `${safeString(cookie.name)}=${safeString(cookie.value)}`;
    const valueSize = (cookie) => safeString(cookie.value).length;
    const valuePreview = (cookie) => {
        const value = safeString(cookie.value);
        if (value.length <= 42) {
            return value;
        }
        return `${value.slice(0, 24)}...${value.slice(-12)}`;
    };
    const expiresText = (cookie) => {
        if (cookie.session) {
            return "session";
        }
        const expiration = Number(cookie.expirationDate);
        if (!Number.isFinite(expiration) || expiration <= 0) {
            return "";
        }
        const date = new Date(expiration * 1000);
        return Number.isNaN(date.getTime()) ? "" : date.toISOString();
    };
    const domainKey = (cookie) => safeString(cookie.domain) || "(no domain)";
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
        const parsed = parseResponse(combined);
        const cookies = parsed.cookies;
        if (cookies.length === 0) {
            return { plaintext: combined };
        }

        const byDomain = cookies.reduce((acc, cookie) => {
            const key = domainKey(cookie);
            if (!acc[key]) {
                acc[key] = [];
            }
            acc[key].push(cookie);
            return acc;
        }, {});

        const domainRows = Object.keys(byDomain).sort().map((domain) => {
            const domainCookies = byDomain[domain];
            const secureCount = domainCookies.filter((cookie) => cookie.secure).length;
            const httpOnlyCount = domainCookies.filter((cookie) => cookie.httpOnly).length;
            const sessionCount = domainCookies.filter((cookie) => cookie.session).length;
            return {
                actions: {
                    plaintext: "",
                    button: {
                        name: "Actions",
                        type: "menu",
                        startIcon: "list",
                        value: [
                            viewDictionary(`Domain summary: ${domain}`, {
                                domain,
                                cookieCount: domainCookies.length,
                                secureCount,
                                httpOnlyCount,
                                sessionCount
                            }),
                            exportString(`Export domain JSON: ${domain}`, {
                                domain,
                                cookieCount: domainCookies.length,
                                cookies: domainCookies
                            })
                        ]
                    }
                },
                domain: { plaintext: domain, copyIcon: true },
                count: { plaintext: String(domainCookies.length) },
                secure: { plaintext: String(secureCount) },
                httpOnly: { plaintext: String(httpOnlyCount) },
                session: { plaintext: String(sessionCount) }
            };
        });

        const cookieRows = cookies
            .slice()
            .sort((a, b) => cookieLabel(a).localeCompare(cookieLabel(b)))
            .map((cookie) => {
                const domainCookies = byDomain[domainKey(cookie)] || [];
                const exportCookie = {
                    ...cookie,
                    cookieHeader: cookieHeader(cookie),
                    valueLength: valueSize(cookie)
                };
                return {
                    rowStyle: cookie.httpOnly ? { backgroundColor: "rgba(33, 150, 243, 0.10)" } : {},
                    actions: {
                        plaintext: "",
                        button: {
                            name: "Actions",
                            type: "menu",
                            startIcon: "list",
                            value: [
                                viewDictionary(`Cookie details: ${cookieLabel(cookie)}`, exportCookie),
                                exportString(`Export cookie JSON: ${cookieLabel(cookie)}`, exportCookie),
                                {
                                    name: "Cookie Header",
                                    type: "string",
                                    value: cookieHeader(cookie),
                                    title: `Cookie header: ${safeString(cookie.name)}`,
                                    startIcon: "list",
                                    hoverText: "Open name=value cookie fragment"
                                },
                                exportString(`Export domain JSON: ${domainKey(cookie)}`, {
                                    domain: domainKey(cookie),
                                    cookieCount: domainCookies.length,
                                    cookies: domainCookies
                                })
                            ]
                        }
                    },
                    domain: { plaintext: safeString(cookie.domain), copyIcon: true },
                    name: { plaintext: safeString(cookie.name), copyIcon: true },
                    path: { plaintext: safeString(cookie.path), copyIcon: true },
                    value: {
                        plaintext: valuePreview(cookie),
                        plaintextHoverText: safeString(cookie.value),
                        copyIcon: true
                    },
                    value_size: { plaintext: String(valueSize(cookie)) },
                    secure: { plaintext: cookie.secure ? "yes" : "" },
                    httpOnly: { plaintext: cookie.httpOnly ? "yes" : "" },
                    hostOnly: { plaintext: cookie.hostOnly ? "yes" : "" },
                    sameSite: { plaintext: safeString(cookie.sameSite) },
                    session: { plaintext: cookie.session ? "yes" : "" },
                    expires: { plaintext: expiresText(cookie) },
                    storeId: { plaintext: safeString(cookie.storeId) }
                };
            });

        return {
            plaintext: `Cookies returned: ${parsed.cookieCount || cookies.length}`,
            table: [
                {
                    headers: [
                        { plaintext: "actions", type: "button", width: 105, disableSort: true },
                        { plaintext: "domain", type: "string", fillWidth: true },
                        { plaintext: "count", type: "number", width: 90 },
                        { plaintext: "secure", type: "number", width: 90 },
                        { plaintext: "httpOnly", type: "number", width: 105 },
                        { plaintext: "session", type: "number", width: 95 }
                    ],
                    rows: domainRows,
                    title: `Cookie domains (${domainRows.length})`
                },
                {
                    headers: [
                        { plaintext: "actions", type: "button", width: 105, disableSort: true },
                        { plaintext: "domain", type: "string", fillWidth: true },
                        { plaintext: "name", type: "string", width: 180 },
                        { plaintext: "path", type: "string", width: 150 },
                        { plaintext: "value", type: "string", fillWidth: true },
                        { plaintext: "value_size", type: "size", width: 120 },
                        { plaintext: "secure", type: "string", width: 80 },
                        { plaintext: "httpOnly", type: "string", width: 95 },
                        { plaintext: "hostOnly", type: "string", width: 95 },
                        { plaintext: "sameSite", type: "string", width: 130 },
                        { plaintext: "session", type: "string", width: 85 },
                        { plaintext: "expires", type: "date", width: 230 },
                        { plaintext: "storeId", type: "string", width: 90 }
                    ],
                    rows: cookieRows,
                    title: `Cookies (${cookies.length})`
                }
            ]
        };
    } catch (error) {
        return { plaintext: combined };
    }
}

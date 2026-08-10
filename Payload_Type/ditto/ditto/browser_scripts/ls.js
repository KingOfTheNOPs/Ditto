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
    const basename = (path) => {
        const text = safeString(path);
        const parts = text.split(/[\\/]/).filter((part) => part.length > 0);
        return parts.length ? parts[parts.length - 1] : text;
    };
    const isoDate = (seconds) => {
        const value = Number(seconds);
        if (!Number.isFinite(value) || value <= 0) {
            return "";
        }
        const date = new Date(value * 1000);
        return Number.isNaN(date.getTime()) ? "" : date.toISOString();
    };
    const fileType = (entry) => {
        if (entry.dir) {
            return "dir";
        }
        const name = safeString(entry.name || entry.path).toLowerCase();
        const ext = name.includes(".") ? name.slice(name.lastIndexOf(".")) : "";
        if ([".zip", ".7z", ".rar", ".cab", ".tar", ".gz"].includes(ext)) {
            return "archive";
        }
        if ([".pem", ".pfx", ".key", ".kdbx", ".rdp", ".ovpn"].includes(ext)) {
            return "key";
        }
        if ([".ps1", ".bat", ".cmd", ".vbs", ".js", ".py", ".config", ".xml", ".json"].includes(ext)) {
            return "script";
        }
        if ([".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf"].includes(ext)) {
            return "doc";
        }
        return "file";
    };
    const rowStyle = (entry) => {
        const type = fileType(entry);
        if (entry.dir) {
            return { backgroundColor: "rgba(33, 150, 243, 0.08)" };
        }
        if (type === "key") {
            return { backgroundColor: "rgba(255, 193, 7, 0.18)" };
        }
        if (type === "script") {
            return { backgroundColor: "rgba(156, 39, 176, 0.10)" };
        }
        return {};
    };

    try {
        const parsed = JSON.parse(combined);
        const body = parsed && parsed.r && typeof parsed.r === "object" ? parsed.r : parsed;
        if (parsed && parsed.ok === false) {
            return { plaintext: safeString(parsed.e || combined) };
        }
        const entries = Array.isArray(body) ? body : (Array.isArray(body.entries) ? body.entries : []);
        const listedPath = safeString((body && body.path) || "");
        if (entries.length === 0) {
            return { plaintext: combined };
        }

        const rows = entries
            .slice()
            .sort((a, b) => {
                if (Boolean(a.dir) !== Boolean(b.dir)) {
                    return a.dir ? -1 : 1;
                }
                return safeString(a.name || a.path).localeCompare(safeString(b.name || b.path));
            })
            .map((entry) => {
                const fullPath = safeString(entry.path);
                const name = safeString(entry.name || basename(fullPath));
                const details = {
                    name,
                    path: fullPath,
                    type: fileType(entry),
                    isDirectory: Boolean(entry.dir),
                    size: entry.len || 0,
                    modified: isoDate(entry.mtime)
                };
                const menu = [
                    {
                        name: "Details",
                        type: "dictionary",
                        value: details,
                        leftColumnTitle: "Field",
                        rightColumnTitle: "Value",
                        title: `File details: ${name}`
                    },
                    {
                        name: "JSON",
                        type: "string",
                        value: JSON.stringify(entry, null, 2),
                        title: `File JSON: ${name}`,
                        startIcon: "download"
                    }
                ];

                if (entry.dir) {
                    menu.push({
                        name: "List Directory",
                        type: "task",
                        startIcon: "list",
                        ui_feature: "file_browser:list",
                        parameters: { path: fullPath }
                    });
                } else {
                    menu.push({
                        name: "Download",
                        type: "task",
                        startIcon: "download",
                        ui_feature: "file_browser:download",
                        parameters: { path: fullPath }
                    });
                }

                return {
                    rowStyle: rowStyle(entry),
                    actions: {
                        plaintext: "",
                        button: {
                            name: "Actions",
                            type: "menu",
                            startIcon: "list",
                            value: menu
                        }
                    },
                    type: { plaintext: fileType(entry) },
                    name: { plaintext: name, copyIcon: true },
                    size: { plaintext: entry.dir ? "" : safeString(entry.len || 0) },
                    modified: { plaintext: isoDate(entry.mtime) },
                    path: { plaintext: fullPath, copyIcon: true }
                };
            });

        return {
            plaintext: `Entries returned: ${entries.length}${listedPath ? ` from ${listedPath}` : ""}`,
            table: [{
                headers: [
                    { plaintext: "actions", type: "button", width: 105, disableSort: true },
                    { plaintext: "type", type: "string", width: 90 },
                    { plaintext: "name", type: "string", width: 240 },
                    { plaintext: "size", type: "size", width: 110 },
                    { plaintext: "modified", type: "date", width: 230 },
                    { plaintext: "path", type: "string", fillWidth: true }
                ],
                rows,
                title: `Directory listing${listedPath ? `: ${listedPath}` : ""}`
            }]
        };
    } catch (error) {
        return { plaintext: combined };
    }
}

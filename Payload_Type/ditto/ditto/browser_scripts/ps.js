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
    const normalizeExe = (value) => safeString(value).replace(/\.exe$/i, "");
    const highlight = (exe) => {
        const name = normalizeExe(exe).toLowerCase();
        if (["powershell", "pwsh", "cmd", "wscript", "cscript", "mshta", "rundll32", "regsvr32"].includes(name)) {
            return { backgroundColor: "rgba(255, 193, 7, 0.18)" };
        }
        if (["lsass", "winlogon", "services", "samss"].includes(name)) {
            return { backgroundColor: "rgba(33, 150, 243, 0.12)" };
        }
        if (["chrome", "msedge", "firefox", "brave", "opera"].includes(name)) {
            return { backgroundColor: "rgba(76, 175, 80, 0.10)" };
        }
        return {};
    };

    try {
        const parsed = JSON.parse(combined);
        const body = parsed && parsed.r && typeof parsed.r === "object" ? parsed.r : parsed;
        if (parsed && parsed.ok === false) {
            return { plaintext: safeString(parsed.e || combined) };
        }
        const processes = Array.isArray(body) ? body : (Array.isArray(body.processes) ? body.processes : []);
        if (processes.length === 0) {
            return { plaintext: combined };
        }

        const rows = processes
            .slice()
            .sort((a, b) => Number(a.pid || 0) - Number(b.pid || 0))
            .map((proc) => {
                const details = {
                    pid: proc.pid,
                    ppid: proc.ppid,
                    threads: proc.threads,
                    exe: proc.exe || proc.name || ""
                };
                return {
                    rowStyle: highlight(proc.exe || proc.name),
                    actions: {
                        plaintext: "",
                        button: {
                            name: "Actions",
                            type: "menu",
                            startIcon: "list",
                            value: [
                                {
                                    name: "Details",
                                    type: "dictionary",
                                    value: details,
                                    leftColumnTitle: "Field",
                                    rightColumnTitle: "Value",
                                    title: `Process ${safeString(proc.pid)}`
                                },
                                {
                                    name: "JSON",
                                    type: "string",
                                    value: JSON.stringify(proc, null, 2),
                                    title: `Process JSON ${safeString(proc.pid)}`,
                                    startIcon: "download"
                                }
                            ]
                        }
                    },
                    pid: { plaintext: safeString(proc.pid), copyIcon: true },
                    ppid: { plaintext: safeString(proc.ppid), copyIcon: true },
                    threads: { plaintext: safeString(proc.threads) },
                    exe: { plaintext: safeString(proc.exe || proc.name), copyIcon: true }
                };
            });

        return {
            plaintext: `Processes returned: ${processes.length}`,
            table: [{
                headers: [
                    { plaintext: "actions", type: "button", width: 105, disableSort: true },
                    { plaintext: "pid", type: "number", width: 95 },
                    { plaintext: "ppid", type: "number", width: 95 },
                    { plaintext: "threads", type: "number", width: 95 },
                    { plaintext: "exe", type: "string", fillWidth: true }
                ],
                rows,
                title: `Processes (${processes.length})`
            }]
        };
    } catch (error) {
        return { plaintext: combined };
    }
}

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

    try {
        const parsed = JSON.parse(combined);
        const tab = parsed.tab || {};
        const agentFileId = parsed.agent_file_id || parsed.file_id;
        const title = tab.title ? String(tab.title) : "Untitled tab";
        const lines = [
            `Captured tab ${tab.id ?? ""}: ${title}`,
            `URL: ${tab.url || ""}`,
            `Window ID: ${tab.windowId ?? ""}`,
            `Status: ${tab.status || ""}`,
            `Captured At: ${parsed.capturedAt || ""}`
        ];

        const result = {
            plaintext: lines.join("\n"),
            table: [{
                headers: [
                    { plaintext: "field", type: "string", width: 130 },
                    { plaintext: "value", type: "string", fillWidth: true }
                ],
                rows: [
                    { field: { plaintext: "tab_id" }, value: { plaintext: String(tab.id ?? ""), copyIcon: true } },
                    { field: { plaintext: "window_id" }, value: { plaintext: String(tab.windowId ?? "") } },
                    { field: { plaintext: "title" }, value: { plaintext: title, copyIcon: true } },
                    { field: { plaintext: "url" }, value: { plaintext: String(tab.url || ""), copyIcon: true } },
                    { field: { plaintext: "status" }, value: { plaintext: String(tab.status || "") } },
                    { field: { plaintext: "file" }, value: { plaintext: String(parsed.filename || agentFileId || "") } }
                ],
                title: "Captured Tab"
            }]
        };

        if (agentFileId) {
            result.screenshot = [{
                agent_file_id: agentFileId,
                variant: "contained",
                name: "Preview Capture",
                hoverText: "View captured tab"
            }];
        }

        return result;
    } catch (error) {
        return { plaintext: combined };
    }
}

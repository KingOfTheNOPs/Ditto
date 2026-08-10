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
        const tabs = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.tabs) ? parsed.tabs : []);
        if (tabs.length === 0) {
            return { plaintext: combined };
        }

        const rows = tabs.map((tab) => {
            const tabId = Number(tab.id);
            return {
                active: { plaintext: tab.active ? "yes" : "" },
                tab_id: { plaintext: String(tab.id ?? ""), copyIcon: true },
                window_id: { plaintext: String(tab.windowId ?? "") },
                title: { plaintext: String(tab.title || ""), copyIcon: true },
                url: { plaintext: String(tab.url || ""), copyIcon: true },
                status: { plaintext: String(tab.status || "") },
                capture: {
                    button: {
                        name: "",
                        type: "task",
                        ui_feature: "browser_tabs:capture",
                        parameters: { tab_id: tabId },
                        hoverText: "Capture this tab",
                        startIcon: "image"
                    }
                },
                rowStyle: tab.active ? { backgroundColor: "rgba(76, 175, 80, 0.16)" } : {}
            };
        });

        return {
            table: [{
                headers: [
                    { plaintext: "active", type: "string", width: 80 },
                    { plaintext: "tab_id", type: "number", width: 90 },
                    { plaintext: "window_id", type: "number", width: 110 },
                    { plaintext: "title", type: "string", fillWidth: true },
                    { plaintext: "url", type: "string", fillWidth: true },
                    { plaintext: "status", type: "string", width: 100 },
                    { plaintext: "capture", type: "button", width: 90, disableSort: true }
                ],
                rows,
                title: `Browser tabs (${tabs.length})`
            }]
        };
    } catch (error) {
        return { plaintext: combined };
    }
}

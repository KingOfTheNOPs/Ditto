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
        const path = String(parsed.path || "");
        const rows = [
            { field: { plaintext: "path" }, value: { plaintext: path, copyIcon: true } },
            { field: { plaintext: "source_file_id" }, value: { plaintext: String(parsed.file_id || parsed.agent_file_id || ""), copyIcon: true } },
            { field: { plaintext: "written" }, value: { plaintext: String(parsed.written ?? "") } },
            { field: { plaintext: "chunks" }, value: { plaintext: String(parsed.chunks ?? "") } }
        ];

        return {
            plaintext: `Uploaded ${parsed.filename || "file"} -> ${path} (${parsed.written ?? 0} bytes)`,
            table: [{
                headers: [
                    { plaintext: "field", type: "string", width: 130 },
                    { plaintext: "value", type: "string", fillWidth: true }
                ],
                rows,
                title: "Uploaded File"
            }]
        };
    } catch (error) {
        return { plaintext: combined };
    }
}

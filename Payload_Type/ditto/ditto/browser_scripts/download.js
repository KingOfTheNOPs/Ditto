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
        const agentFileId = parsed.agent_file_id || parsed.file_id;
        const fileName = String(parsed.filename || parsed.path || task.display_params || "download.bin")
            .split(/[\\/]/)
            .pop() || "download.bin";
        const rows = [
            { field: { plaintext: "path" }, value: { plaintext: String(parsed.path || ""), copyIcon: true } },
            { field: { plaintext: "filename" }, value: { plaintext: fileName, copyIcon: true } },
            { field: { plaintext: "file_id" }, value: { plaintext: String(agentFileId || ""), copyIcon: true } },
            { field: { plaintext: "size" }, value: { plaintext: String(parsed.file_len ?? parsed.size ?? "") } },
            { field: { plaintext: "chunks" }, value: { plaintext: String(parsed.chunks ?? "") } }
        ];

        const result = {
            plaintext: agentFileId
                ? `Downloaded ${parsed.path || fileName} (${parsed.file_len ?? parsed.size ?? 0} bytes)`
                : combined,
            table: [{
                headers: [
                    { plaintext: "field", type: "string", width: 120 },
                    { plaintext: "value", type: "string", fillWidth: true }
                ],
                rows,
                title: "Downloaded File"
            }]
        };

        if (agentFileId) {
            result.media = [{
                filename: fileName,
                agent_file_id: agentFileId
            }];
            result.download = [{
                agent_file_id: agentFileId,
                variant: "contained",
                name: `Download ${fileName}`
            }];
        }

        return result;
    } catch (error) {
        return { plaintext: combined };
    }
}

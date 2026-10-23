/* SPDX-License-Identifier: Apache-2.0 */
#include "lib/mshv.h"

int main(int argc, char **argv)
{
    const struct vv_test_suite suite = {
        .contract = VV_MSHV_CONTRACT,
        .protocol_prefix = "MSHV",
        .begin = __start_mshv_registry,
        .end = __stop_mshv_registry,
        .context_size = sizeof(struct mshv_fixture),
        .preflight = mshv_preflight,
        .init_context = mshv_init_context,
        .cleanup = mshv_cleanup_context,
    };
    return vv_appliance_main(argc, argv, &suite);
}

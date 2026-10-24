/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0008 - Mismatched file descriptor IOCTL routing rejection.
 *
 * Verify that each IOCTL is rejected with ENOTTY when invoked on
 * the wrong descriptor type. Partition and virtual processor requests
 * sent to a device descriptor must return ENOTTY. Device and virtual
 * processor requests sent to a partition descriptor must return ENOTTY.
 * Device and partition requests sent to a virtual processor descriptor
 * must return ENOTTY.
 *
 * Following all rejections, confirm operational continuity with a valid
 * four register roundtrip.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t mismatched_routing(struct mshv_fixture *f)
{
    char op[128];

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    for (size_t i = 0; i < mshv_ioctl_count; ++i) {
        const struct mshv_ioctl_entry *entry = &mshv_ioctl_table[i];
        if (!(entry->targets & VV_IOCTL_DEVICE)) {
            snprintf(op, sizeof(op), "%s on device fd", entry->name);
            if (mshv_expect_ioctl(f->device, entry->request, NULL,
                                  op, ENOTTY) != TEST_PASS)
                return TEST_FAIL;
        }
        if (!(entry->targets & VV_IOCTL_PARTITION)) {
            snprintf(op, sizeof(op), "%s on partition fd", entry->name);
            if (mshv_expect_ioctl(f->partition, entry->request, NULL,
                                  op, ENOTTY) != TEST_PASS)
                return TEST_FAIL;
        }
        if (!(entry->targets & VV_IOCTL_VP)) {
            snprintf(op, sizeof(op), "%s on VP fd", entry->name);
            if (mshv_expect_ioctl(f->vp, entry->request, NULL,
                                  op, ENOTTY) != TEST_PASS)
                return TEST_FAIL;
        }
    }

    return mshv_roundtrip(f, 4, VV_GPR_SEED_MISMATCHED_ROUTING);
}

REGISTER_MSHV_TEST(ML0008, mismatched_routing,
                   "Mismatched descriptor routing rejection across all defined IOCTLs");

/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0010 - Pointer argument fault validation on valid descriptors.
 *
 * Verify that invoking pointer expecting IOCTLs with a NULL argument
 * returns EFAULT on valid open descriptors. For SEV SNP partition
 * requests, verify that EOPNOTSUPP is returned on standard partitions.
 *
 * Following all fault rejections, confirm operational continuity with
 * a valid four register roundtrip.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t null_pointer_faults(struct mshv_fixture *f)
{
    char op[128];

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    const int fds[] = {f->device, f->partition, f->vp};
    const unsigned targets[] = {VV_IOCTL_DEVICE, VV_IOCTL_PARTITION, VV_IOCTL_VP};
    const char *descriptions[] = {"device", "partition", "VP"};
    for (size_t i = 0; i < mshv_ioctl_count; ++i) {
        const struct mshv_ioctl_entry *entry = &mshv_ioctl_table[i];
        if (!entry->null_errno)
            continue;
        for (size_t target = 0; target < sizeof(fds) / sizeof(fds[0]); ++target) {
            if (!(entry->targets & targets[target]))
                continue;
            snprintf(op, sizeof(op), "%s NULL on %s fd", entry->name, descriptions[target]);
            if (mshv_expect_ioctl(fds[target], entry->request, NULL, op,
                                  entry->null_errno) != TEST_PASS)
                return TEST_FAIL;
        }
    }

    return mshv_roundtrip(f, 4, VV_GPR_SEED_NULL_POINTER_FAULTS);
}

REGISTER_MSHV_TEST(ML0010, null_pointer_faults,
                   "Pointer argument fault validation across valid descriptor types");

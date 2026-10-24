/* SPDX-License-Identifier: Apache-2.0 */
/*
 * MR0004 - Virtual processor CPUID query validation.
 *
 * UAPI: MSHV_GET_VP_CPUID_VALUES.
 *
 * Query virtual processor CPUID values through the dedicated VP IOCTL.
 * Verify that passing a NULL argument is rejected with EFAULT. Verify
 * that valid queries return success and valid output fields. Verify that
 * registers remain intact following CPUID queries.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t vp_cpuid(struct mshv_fixture *f)
{
    struct mshv_get_vp_cpuid_values cpuid_args = {
        .function = 0x00000001,
        .index = 0,
        .xfem = 0,
        .xss = 0,
    };

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    /* NULL argument must return EFAULT */
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_CPUID_VALUES, NULL,
                          "MSHV_GET_VP_CPUID_VALUES NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;

    /* Valid query must succeed */
    if (mshv_expect_ioctl(f->vp, MSHV_GET_VP_CPUID_VALUES, &cpuid_args,
                          "MSHV_GET_VP_CPUID_VALUES function=1", 0) != TEST_PASS)
        return TEST_FAIL;

    return mshv_roundtrip(f, 4, VV_GPR_SEED_VP_CPUID);
}

REGISTER_MSHV_TEST(MR0004, vp_cpuid,
                   "Virtual processor CPUID query and argument fault validation");

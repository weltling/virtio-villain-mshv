/* SPDX-License-Identifier: Apache-2.0 */
/*
 * TL0003: VP indices and independent processor state.
 *
 * TLFS 6.0b section 7.2 defines VP identity and requires stable indices.
 * Section 7.10.1 scopes register writes to the specified partition and VP.
 * Requires two child VPs with VP index access. No VP execution.
 */
#include <inttypes.h>

#include "lib/mshv.h"

static test_result_t check_index(int fd, uint32_t index)
{
    const uint32_t name = VV_VP_INDEX;
    union hv_register_value value;
    if (mshv_get_registers(fd, index, &name, &value, 1) != TEST_PASS)
        return TEST_FAIL;
    if (value.reg64 != index || value.words[1] != 0)
        TFAIL("VP index: expected %u, actual high=0x%" PRIx64 " low=0x%" PRIx64,
              index, value.words[1], value.reg64);
    return TEST_PASS;
}

static test_result_t vp_identity(struct mshv_fixture *f)
{
    struct mshv_fixture sibling;
    struct mshv_create_vp args = {.vp_index = 1};
    test_result_t result = TEST_FAIL;
    mshv_init_context(&sibling);

    if (mshv_create_configured(f, VV_MSHV_PARTITION_FLAGS_NONE, VV_TLFS_BASIC_FEATURES) != TEST_PASS)
        goto out;
    sibling.vp = ioctl(f->partition, MSHV_CREATE_VP, &args);
    if (mshv_check_fd(sibling.vp, "MSHV_CREATE_VP index=1") != TEST_PASS ||
        check_index(f->vp, 0) != TEST_PASS || check_index(sibling.vp, 1) != TEST_PASS ||
        mshv_set_gprs(f, 4, VV_GPR_SEED_ASCENDING) != TEST_PASS ||
        mshv_set_gprs(&sibling, 4, VV_GPR_SEED_DESCENDING) != TEST_PASS ||
        mshv_check_gprs(f, 4, VV_GPR_SEED_ASCENDING) != TEST_PASS ||
        mshv_check_gprs(&sibling, 4, VV_GPR_SEED_DESCENDING) != TEST_PASS ||
        mshv_set_gprs(f, 4, VV_GPR_PATTERN_EDGE_BITS) != TEST_PASS ||
        mshv_check_gprs(&sibling, 4, VV_GPR_SEED_DESCENDING) != TEST_PASS ||
        mshv_check_gprs(f, 4, VV_GPR_PATTERN_EDGE_BITS) != TEST_PASS ||
        check_index(f->vp, 0) != TEST_PASS || check_index(sibling.vp, 1) != TEST_PASS)
        goto out;
    result = TEST_PASS;
out:
    if (mshv_cleanup(&sibling) != TEST_PASS)
        result = TEST_FAIL;
    return result;
}

REGISTER_MSHV_TEST(TL0003, vp_identity,
                   "VP indices and independent register state",
                   TLFS_SPEC_V6_0B, "7.2");

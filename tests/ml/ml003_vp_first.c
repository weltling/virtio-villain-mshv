/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML003 - Closing a virtual processor (VP) FD does not release its index.
 *
 * UAPI: MSHV_CREATE_VP index ownership after closing the VP descriptor.
 *
 * Create VP zero, then close its file descriptor (FD) while retaining the
 * partition. Recreating index zero must return -1/EEXIST because the partition
 * still owns that VP. Creating VP one must succeed. Its RAX set/get must
 * preserve 0x1020304050607080, proving continued usability after rejection.
 * Index reuse is not expected before partition destruction.
 */
#include <errno.h>
#include "lib/mshv.h"

static test_result_t vp_first(struct mshv_fixture *f)
{
    struct mshv_create_vp vp = {.vp_index = 0};
    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_close(&f->vp, "close VP before partition") != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_CREATE_VP, &vp,
                          "closed VP remains allocated until partition destruction",
                          EEXIST) != TEST_PASS)
        return TEST_FAIL;
    vp.vp_index = 1;
    f->vp = ioctl(f->partition, MSHV_CREATE_VP, &vp);
    if (mshv_check_fd(f->vp, "MSHV_CREATE_VP index=%u after EEXIST", vp.vp_index) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(f, 1, 0x1020304050607080ULL);
}

REGISTER_MSHV_TEST(ML003, vp_first, "VP-first closure, exact EEXIST, then usable new VP");

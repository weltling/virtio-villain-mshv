/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML0013 - Partition property configuration and query validation.
 *
 * UAPI: MSHV_GET_PARTITION_PROPERTY, MSHV_SET_PARTITION_PROPERTY.
 *
 * Verify that partition property query and update IOCTLs enforce valid
 * user memory pointers by rejecting NULL arguments with EFAULT.
 *
 * Following all rejections, confirm that general purpose registers remain
 * undamaged.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>

#include "lib/mshv.h"

static test_result_t partition_property(struct mshv_fixture *f)
{
    struct mshv_partition_property prop = {
        .property_code = 0x00000001,
        .property_value = 0,
    };

    if (mshv_create(f) != TEST_PASS)
        return TEST_FAIL;

    /* NULL argument must return EFAULT */
    if (mshv_expect_ioctl(f->partition, MSHV_GET_PARTITION_PROPERTY, NULL,
                          "MSHV_GET_PARTITION_PROPERTY NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;
    if (mshv_expect_ioctl(f->partition, MSHV_SET_PARTITION_PROPERTY, NULL,
                          "MSHV_SET_PARTITION_PROPERTY NULL", EFAULT) != TEST_PASS)
        return TEST_FAIL;

    /* Query with valid buffer structure */
    ioctl(f->partition, MSHV_GET_PARTITION_PROPERTY, &prop);

    return mshv_roundtrip(f, 4, VV_GPR_SEED_PARTITION_PROPERTY);
}

REGISTER_MSHV_TEST(ML0013, partition_property,
                   "Partition property query and update pointer validation");

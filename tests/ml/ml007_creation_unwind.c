/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML007 - Recover from late partition and VP descriptor allocation failures.
 *
 * The selected driver's creation paths allocate hypervisor resources before
 * get_unused_fd_flags(). Temporarily setting the process soft RLIMIT_NOFILE
 * to zero forces EMFILE there without filling the guest descriptor table.
 * Existing descriptors remain usable. Restore the limit after every IOCTL.
 *
 * Keep B alive across 64 cycles of eight rejected partition creations and
 * eight rejected VP-one creations in A. Check B before any write can hide
 * damage. Successful creation after each burst checks observable recovery,
 * including reuse of the VP index whose creation failed. Alternate A's
 * closure order. No tracing, kernel fault injection or host changes are used.
 * Passing does not prove complete hypervisor resource reclamation.
 */
#include <errno.h>
#include <inttypes.h>
#include <string.h>
#include <sys/resource.h>

#include "lib/mshv.h"

enum {
    UNWIND_CYCLES = 64,
    UNWIND_ATTEMPTS = 8,
    UNWIND_REGISTERS = 4,
};

static test_result_t reject_creation(int fd, unsigned long request, void *args,
                                     const char *operation, const struct rlimit *saved,
                                     int *created)
{
    struct rlimit limited = *saved;
    limited.rlim_cur = 0;
    if (setrlimit(RLIMIT_NOFILE, &limited) != 0)
        TFAIL("setrlimit RLIMIT_NOFILE soft=0: actual -1 errno=%d (%s)",
              errno, strerror(errno));
    errno = 0;
    *created = ioctl(fd, request, args);
    int error = errno;
    if (setrlimit(RLIMIT_NOFILE, saved) != 0)
        TFAIL("restore RLIMIT_NOFILE soft=%ju hard=%ju: actual -1 errno=%d (%s)",
              (uintmax_t)saved->rlim_cur, (uintmax_t)saved->rlim_max,
              errno, strerror(errno));
    if (*created != -1 || error != EMFILE)
        TFAIL("%s fd=%d soft RLIMIT_NOFILE=0: expected rc=-1 errno=%d (%s), "
              "actual rc=%d errno=%d (%s)",
              operation, fd, EMFILE, strerror(EMFILE), *created, error, strerror(error));
    return TEST_PASS;
}

static test_result_t creation_unwind(struct mshv_fixture *b)
{
    struct rlimit saved;
    struct mshv_fixture a;
    struct mshv_create_partition partition = {
        .pt_flags = VV_MSHV_PARTITION_FLAGS_NONE,
        .pt_isolation = MSHV_PT_ISOLATION_NONE,
    };
    struct mshv_create_vp vp = {.vp_index = 1};
    uint64_t seed = VV_GPR_SEED_DESCENDING;
    test_result_t result = TEST_FAIL;
    mshv_init_context(&a);

    if (getrlimit(RLIMIT_NOFILE, &saved) != 0)
        TFAIL("getrlimit RLIMIT_NOFILE: actual -1 errno=%d (%s)", errno, strerror(errno));
    if (mshv_create(b) != TEST_PASS ||
        mshv_roundtrip(b, UNWIND_REGISTERS, seed) != TEST_PASS)
        goto out;
    for (unsigned cycle = 0; cycle < UNWIND_CYCLES; ++cycle) {
        printf("mshv-unwind cycle %u/%u: %u partition failures flags=0x%" PRIx64
               " isolation=0x%" PRIx64 "\n",
               cycle + 1, (unsigned)UNWIND_CYCLES, (unsigned)UNWIND_ATTEMPTS,
               (uint64_t)partition.pt_flags, (uint64_t)partition.pt_isolation);
        for (unsigned attempt = 0; attempt < UNWIND_ATTEMPTS; ++attempt) {
            if (reject_creation(b->device, MSHV_CREATE_PARTITION, &partition,
                                "MSHV_CREATE_PARTITION", &saved, &a.partition) != TEST_PASS ||
                mshv_check_gprs(b, UNWIND_REGISTERS, seed) != TEST_PASS)
                goto out;
        }
        if (mshv_create(&a) != TEST_PASS ||
            mshv_close(&a.vp, "close A VP zero before VP one creation") != TEST_PASS)
            goto out;
        printf("mshv-unwind cycle %u/%u: %u VP failures index=%u\n",
               cycle + 1, (unsigned)UNWIND_CYCLES, (unsigned)UNWIND_ATTEMPTS, vp.vp_index);
        for (unsigned attempt = 0; attempt < UNWIND_ATTEMPTS; ++attempt) {
            if (reject_creation(a.partition, MSHV_CREATE_VP, &vp,
                                "MSHV_CREATE_VP index=1", &saved, &a.vp) != TEST_PASS ||
                mshv_check_gprs(b, UNWIND_REGISTERS, seed) != TEST_PASS)
                goto out;
        }
        a.vp = ioctl(a.partition, MSHV_CREATE_VP, &vp);
        if (mshv_check_fd(a.vp, "MSHV_CREATE_VP index=%u after EMFILE", vp.vp_index) != TEST_PASS ||
            mshv_roundtrip(&a, UNWIND_REGISTERS, ~seed) != TEST_PASS)
            goto out;
        if (cycle % 2) {
            if (mshv_close(&a.device, "close A device before partition") != TEST_PASS ||
                mshv_close(&a.partition, "close A partition before VP one") != TEST_PASS ||
                mshv_check_gprs(&a, UNWIND_REGISTERS, ~seed) != TEST_PASS)
                goto out;
        }
        if (mshv_cleanup(&a) != TEST_PASS ||
            mshv_check_gprs(b, UNWIND_REGISTERS, seed) != TEST_PASS)
            goto out;
        seed ^= VV_GPR_CYCLE_XOR + cycle;
        if (mshv_roundtrip(b, UNWIND_REGISTERS, seed) != TEST_PASS)
            goto out;
    }
    printf("mshv-unwind completed %u cycles, %u partition and %u VP EMFILE failures\n",
           (unsigned)UNWIND_CYCLES, (unsigned)(UNWIND_CYCLES * UNWIND_ATTEMPTS),
           (unsigned)(UNWIND_CYCLES * UNWIND_ATTEMPTS));
    result = TEST_PASS;
out:
    if (setrlimit(RLIMIT_NOFILE, &saved) != 0) {
        printf("vv-fail %s:%d: final restore RLIMIT_NOFILE soft=%ju hard=%ju: "
               "actual -1 errno=%d (%s)\n",
               __FILE__, __LINE__, (uintmax_t)saved.rlim_cur, (uintmax_t)saved.rlim_max,
               errno, strerror(errno));
        result = TEST_FAIL;
    }
    if (mshv_cleanup(&a) != TEST_PASS)
        result = TEST_FAIL;
    return result;
}

REGISTER_MSHV_TEST(ML007, creation_unwind,
                   "Partition and VP recovery after repeated late descriptor allocation failures");

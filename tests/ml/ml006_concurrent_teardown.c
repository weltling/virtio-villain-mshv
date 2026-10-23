/* SPDX-License-Identifier: Apache-2.0 */
/*
 * ML006 - Partition teardown concurrent with another partition's VP access.
 *
 * Keep partition B and its VP zero alive in the main thread. A worker thread
 * runs 64 lifecycles of partition A, each also using VP zero. Each A cycle
 * performs a four GPR roundtrip, then alternates VP-first teardown with
 * closing both parents before a final check through the VP.
 *
 * The main thread repeatedly checks B's current four GPR values, writes a
 * new pattern and checks it again until the worker finishes. Each A cycle
 * starts only after B completes another iteration, so all cycles overlap
 * B's register access. After joining the worker, B is checked again before
 * any further write. Any failure stops both threads and fails the test.
 *
 * This runs both threads in one appliance kernel. Scheduling remains
 * nondeterministic. Descriptor closure does not prove complete hypervisor
 * resource reclamation.
 */
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <string.h>

#include "lib/mshv.h"

enum {
    CONCURRENT_CYCLES = 64,
    CONCURRENT_REGISTERS = 4,
};

struct churn {
    pthread_barrier_t start;
    atomic_bool stop;
    atomic_bool done;
    atomic_uint cycles;
    atomic_uint b_iterations;
    test_result_t result;
};

static void *churn_partitions(void *arg)
{
    struct churn *w = arg;
    struct mshv_fixture a;
    test_result_t result = TEST_FAIL;
    unsigned seen = 0;
    mshv_init_context(&a);

    pthread_barrier_wait(&w->start);
    for (unsigned i = 0; i < CONCURRENT_CYCLES; ++i) {
        while (atomic_load(&w->b_iterations) == seen && !atomic_load(&w->stop))
            sched_yield();
        if (atomic_load(&w->stop))
            break;
        seen = atomic_load(&w->b_iterations);
        uint64_t seed = VV_GPR_SEED_ASCENDING ^ ((uint64_t)(i + 1) << 40);
        printf("mshv-concurrency A cycle %u/%u create with VP index=0, close %s\n",
               i + 1, (unsigned)CONCURRENT_CYCLES, i % 2 ? "parents first" : "VP first");
        if (mshv_create(&a) != TEST_PASS ||
            mshv_roundtrip(&a, CONCURRENT_REGISTERS, seed) != TEST_PASS)
            goto out;
        if (i % 2) {
            if (mshv_close(&a.device, "close A device before partition") != TEST_PASS ||
                mshv_close(&a.partition, "close A partition before VP") != TEST_PASS ||
                mshv_check_gprs(&a, CONCURRENT_REGISTERS, seed) != TEST_PASS)
                goto out;
        }
        if (mshv_cleanup(&a) != TEST_PASS)
            goto out;
        atomic_store(&w->cycles, i + 1);
    }
    result = TEST_PASS;
out:
    if (mshv_cleanup(&a) != TEST_PASS)
        result = TEST_FAIL;
    w->result = result;
    atomic_store(&w->done, true);
    return NULL;
}

static test_result_t concurrent_teardown(struct mshv_fixture *b)
{
    struct churn w = {.result = TEST_FAIL};
    pthread_t thread;
    test_result_t result = TEST_FAIL;
    uint64_t seed = VV_GPR_SEED_DESCENDING;

    printf("mshv-concurrency create persistent B with VP index=0\n");
    if (mshv_create(b) != TEST_PASS ||
        mshv_roundtrip(b, CONCURRENT_REGISTERS, seed) != TEST_PASS)
        return TEST_FAIL;
    int rc = pthread_barrier_init(&w.start, NULL, 2);
    if (rc != 0)
        TFAIL("pthread_barrier_init count=2: expected 0, actual %d (%s)", rc, strerror(rc));
    rc = pthread_create(&thread, NULL, churn_partitions, &w);
    if (rc != 0) {
        pthread_barrier_destroy(&w.start);
        TFAIL("pthread_create A worker: expected 0, actual %d (%s)", rc, strerror(rc));
    }
    pthread_barrier_wait(&w.start);
    while (!atomic_load(&w.done)) {
        unsigned iteration = atomic_load(&w.b_iterations);
        if (mshv_check_gprs(b, CONCURRENT_REGISTERS, seed) != TEST_PASS)
            goto stop;
        seed = VV_GPR_SEED_DESCENDING ^ ((uint64_t)(iteration + 1) << 32);
        if (mshv_set_gprs(b, CONCURRENT_REGISTERS, seed) != TEST_PASS ||
            mshv_check_gprs(b, CONCURRENT_REGISTERS, seed) != TEST_PASS)
            goto stop;
        atomic_store(&w.b_iterations, iteration + 1);
    }
    result = TEST_PASS;
stop:
    atomic_store(&w.stop, true);
    rc = pthread_join(thread, NULL);
    if (rc != 0) {
        printf("vv-fail %s:%d: pthread_join A worker: expected 0, actual %d (%s)\n",
               __FILE__, __LINE__, rc, strerror(rc));
        return TEST_FAIL;
    }
    pthread_barrier_destroy(&w.start);
    unsigned cycles = atomic_load(&w.cycles);
    printf("mshv-concurrency A completed %u/%u cycles, B completed %u iterations\n",
           cycles, (unsigned)CONCURRENT_CYCLES, atomic_load(&w.b_iterations));
    if (result != TEST_PASS || w.result != TEST_PASS)
        return TEST_FAIL;
    if (cycles != CONCURRENT_CYCLES)
        TFAIL("A worker cycles: expected %u, actual %u", (unsigned)CONCURRENT_CYCLES, cycles);
    printf("mshv-concurrency check B after A worker exit\n");
    if (mshv_check_gprs(b, CONCURRENT_REGISTERS, seed) != TEST_PASS)
        return TEST_FAIL;
    return mshv_roundtrip(b, CONCURRENT_REGISTERS, seed ^ VV_GPR_LOW32_MASK);
}

REGISTER_MSHV_TEST(ML006, concurrent_teardown,
                   "Partition teardown concurrent with another partition's VP access");

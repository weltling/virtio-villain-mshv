# SPDX-License-Identifier: Apache-2.0
TARGET ?= target
SUITE_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
VV_ROOT ?= $(abspath $(SUITE_ROOT)/../virtio-villain)
KERNEL_CONFIGS ?=
KERNEL_ARGS ?=

.DEFAULT_GOAL := initramfs

SUITE := $(CURDIR)
SUITE_BUILD_GOALS = $(filter init initramfs kernel,$(MAKECMDGOALS)) \
  $(if $(filter mshv mshv-initramfs,$(MAKECMDGOALS)),initramfs)
ifneq ($(filter init initramfs kernel mshv mshv-initramfs,$(MAKECMDGOALS))$(if $(MAKECMDGOALS),,default),)
include $(VV_ROOT)/lib/suite.mk
endif

mshv mshv-initramfs: initramfs

clean:
	python3 "$(VV_ROOT)/lib/python/villain/clean.py" --root "$(CURDIR)" "$(TARGET)"

selftest:
	python3 -m unittest discover -s selftest -p 'test_*.py'

lint:
	python3 -m flake8 run lib selftest

help:
	@echo "Targets:"
	@echo "  init                Build the MSHV test executable"
	@echo "  initramfs           Build and package the executable as /init (default)"
	@echo "  mshv, mshv-initramfs Aliases for initramfs"
	@echo "  kernel              Build the selected Linux source offline"
	@echo "  selftest            Run host tests without booting an appliance"
	@echo "  lint                Run Python lint"
	@echo "  clean               Remove the entire selected output directory"
	@echo "  help                Show this message"
	@echo ""
	@echo "Build variables:"
	@echo "  VV_ROOT             Framework checkout (current: $(VV_ROOT))"
	@echo "  MSHV_SOURCE         Required kernel source directory (current: $(or $(MSHV_SOURCE),not set))"
	@echo "  TARGET              Output directory (default: target)"
	@echo "  CC, CFLAGS, LDFLAGS  C compiler and build flags"
	@echo "  V=1                 Print compiler commands in framework and kernel builds"
	@echo "  KERNEL_CONFIGS      Optional ordered config files or fragments"
	@echo "                      Default: MSHV_SOURCE/Microsoft/configs/x86/mshv_defconfig"
	@echo "                      Kconfig adjustments to the default are reported"
	@echo "                      Required appliance options remain strict"
	@echo "                      A nonempty list replaces the default config"
	@echo "                      Explicit custom configs are checked strictly"
	@echo "                      Later files override earlier values"
	@echo "  KERNEL_ARGS         Extra build-kernel options, processed after KERNEL_CONFIGS"
	@echo "                      Use --output DIR for a different config or toolchain"
	@echo "                      Use --jobs N to override the CPU count"
	@echo "  RUSTC               Kernel Rust compiler (default: false for C configurations)"
	@echo "                      Set RUSTC=rustc for a compatible custom Rust config"
	@echo ""
	@echo "Examples:"
	@echo '  make -j init initramfs'
	@echo '  make kernel MSHV_SOURCE=/path/linux'
	@echo '  make kernel MSHV_SOURCE=/path/linux KERNEL_CONFIGS="/path/base.config /path/extra.config" KERNEL_ARGS="--output /path/custom-kernel"'
	@echo '  $(VV_ROOT)/build-kernel --help lists all generic kernel build options'
	@echo ""
	@echo "Relative paths are resolved from this suite directory."
	@echo "clean also removes cached boot components, kernel caches and saved results in TARGET."
	@echo "Keep reusable boot inputs outside TARGET and select them with MSHV_ESP."
	@echo "Use ./run --help for execution options."

.PHONY: init initramfs mshv mshv-initramfs kernel clean selftest lint help

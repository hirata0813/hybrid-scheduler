load("@rules_foreign_cc//foreign_cc:defs.bzl", "make")

# The libbpf source code. This is encompassed by the `:source` filegroup, but
# the `make` rule below wants just the library source passed via the
# `lib_source` parameter.
filegroup(
    name = "libbpf_source",
    srcs = glob(["tools/lib/bpf/**"]),
    visibility = ["//visibility:private"],
)

# The bpftool source code. This is encompassed by the `:source` filegroup, but
# the `make` rule below wants just the library source passed via the
# `lib_source` parameter.
filegroup(
    name = "bpftool_source",
    srcs = glob(["tools/bpf/bpftool/**"]),
    visibility = ["//visibility:private"],
)

# The Linux source code.
filegroup(
    name = "source",
    srcs = glob(["**"]),
    visibility = ["//visibility:private"],
)

# Compiles the libbpf static library.
make(
    name = "libbpf",
    lib_source = ":libbpf_source",
    build_data = [":source"],
    targets = ["libbpf.a"],
    postfix_script =
        "cp $EXT_BUILD_ROOT/external/linux/tools/lib/bpf/libbpf.a $INSTALLDIR/lib/libbpf.a; " +
        "mkdir $INSTALLDIR/include/libbpf; " +
        "cp $EXT_BUILD_ROOT/external/linux/tools/lib/bpf/*.h $INSTALLDIR/include/libbpf; " +
        "sed -i '/enum bpf_stats_type;/d; /bpf_enable_stats/d' $INSTALLDIR/include/libbpf/bpf.h",

    visibility = ["//visibility:public"],
)

# Compiles the bpftool binary.
make(
    name = "bpftool",
    lib_source = ":bpftool_source",
    out_binaries = ["bpftool"],
    build_data = [":source"],
    targets = [""],
    postfix_script =
        "cp $EXT_BUILD_ROOT/external/linux/tools/bpf/bpftool/bpftool " +
        "$INSTALLDIR/bin/bpftool",
    visibility = ["//visibility:public"],
)

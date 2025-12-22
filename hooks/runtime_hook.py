# 运行时钩子 - 修复 numpy CPU dispatcher 问题
import os
import sys

# 必须在加载 numpy 之前设置
os.environ['NPY_DISABLE_CPU_FEATURES'] = ''
os.environ['NUMPY_DISABLE_CPU_DISPATCHER'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

# 禁用 numpy 的新特性检测
os.environ['NPY_DISABLE_SVE'] = '1'

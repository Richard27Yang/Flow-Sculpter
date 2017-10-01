
import tensorflow as tf
import fnmatch
import os

NOT_PATH_ANY = ['base_dir_flow', 'base_dir_boundary', 'batch_size', 'display_test', 'test_set', 'max_steps', 'test_set', 'boundary_learn_loss', 'shape', 'boundary_learn_loss', 'boundary_learn_lr', 'boundary_learn_steps', 'lb_seq_length', 'obj_size','nr_gpus']
NOT_PATH_FLOW = NOT_PATH_ANY + ['nr_boundary_params', 'boundary_model']
NOT_PATH_BOUNDARY = NOT_PATH_ANY + ['flow_model', 'filter_size', 'nr_downsamples', 'nr_res_blocks', 'gated_res', 'nonlinearity', 'div_constant', 'tau', 'density']

def make_checkpoint_path(base_path, FLAGS, network="flow"):
  # make checkpoint path with all the flags specifing different directories
  if network == "flow":
    not_path = NOT_PATH_FLOW
  elif network == "boundary":
    not_path = NOT_PATH_BOUNDARY
  # run through all params and add them to the base path
  for k, v in FLAGS.__dict__['__flags'].items():
    if k not in not_path:
      base_path = base_path + '/' + k + '.' + str(v)
  return base_path

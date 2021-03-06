from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import math
import time
import cv2
import csv
import re
from glob import glob as glb
from tqdm import *
import os

import numpy as np
import tensorflow as tf

import sys
sys.path.append('../')

import model.flow_net as flow_net 
from model.pressure import calc_force
from utils.experiment_manager import make_checkpoint_path

import matplotlib.pyplot as plt

FLAGS = tf.app.flags.FLAGS

# video init
shape = FLAGS.shape.split('x')
shape = map(int, shape)
batch_size= 1
fig_pos = 0

batch_size=1
std = 0.05

fourcc = cv2.cv.CV_FOURCC('m', 'p', '4', 'v') 
video = cv2.VideoWriter()

success = video.open('figs/' + FLAGS.boundary_learn_loss + '_video.mov', fourcc, 10, (2*shape[1], shape[0]), True)

FLOW_DIR = make_checkpoint_path(FLAGS.base_dir_flow, FLAGS, network="flow")
BOUNDARY_DIR = make_checkpoint_path(FLAGS.base_dir_boundary_flow, FLAGS, network="boundary")
print("flow dir is " + FLOW_DIR)
print("boundary dir is " + BOUNDARY_DIR)

def simulated_annealing_step(param_old, fittness_old, param_new, fittness_new, temp=0.1, min_temp=0.00001, alpha=0.999):
  ap = np.exp((fittness_old - fittness_new)/temp)
  print("new fittness " + str(fittness_new))
  print("old fittness " + str(fittness_old))
  print("prob is " + str(ap))
  print("temp is " + str(temp))
  if np.random.rand() < ap:
    print("choose new")
    param = param_new
    fittness = fittness_new
  else:
    print("choose old")
    param = param_old
    fittness = fittness_old
  temp = temp * alpha 
  return param, fittness, temp

def distort_param(param, std):
  param = param + np.random.normal(loc=0.0, scale=std, size=param.shape)
  param = np.minimum(np.maximum(param, -0.5), 0.5)
  return param

def evaluate():
  """Run Eval once.

  Args:
    saver: Saver.
    summary_writer: Summary writer.
    top_k_op: Top K op.
    summary_op: Summary op.
  """
  num_angles = 4
  max_angle =  0.2
  min_angle = -0.1
  set_params          = np.array(num_angles*[FLAGS.nr_boundary_params*[0.0]])
  set_params[:,:]     = 0.0
  set_params_pos      = np.array(num_angles*[FLAGS.nr_boundary_params*[0.0]])
  set_params_pos[:,:] = 1.0

  for i in xrange(num_angles):
    set_params[i,0]      = -i 
  set_params[:,0] = ((max_angle - min_angle) * (set_params[:,0]/num_angles)) - min_angle

  set_params[:,1]      = 0.5
  set_params[:,2]      = 1.0
  set_params[:,-1]     = 0.0

  set_params_pos[:,0]  = 0.0 # set angle to 0.0
  set_params_pos[:,1]  = 0.0 # set n_1 to .5
  set_params_pos[:,2]  = 0.0 # set n_2 to 1.0
  set_params_pos[:,-1] = 0.0 # set tail hieght to 0.0

  with tf.Graph().as_default():
    # Make image placeholder
    params_op, params_op_init, params_op_set, squeeze_loss = flow_net.inputs_boundary_learn(batch_size, set_params=set_params, set_params_pos=set_params_pos, noise_std=0.001)

    # Make boundary
    boundary = flow_net.inference_boundary(batch_size*set_params.shape[0], FLAGS.dims*[FLAGS.obj_size], params_op, full_shape=shape)
    sharp_boundary = tf.round(boundary)

    # predict steady flow on boundary
    predicted_flow = flow_net.inference_network(boundary)
    predicted_sharp_flow = flow_net.inference_network(sharp_boundary)

    # quantities to optimize
    force = calc_force(boundary, predicted_flow[:,:,:,2:3])
    sharp_force = calc_force(sharp_boundary, predicted_sharp_flow[:,:,:,2:3])
    drag_x = tf.reduce_sum(force[:,:,:,0], axis=[1,2])/batch_size
    drag_y = tf.reduce_sum(force[:,:,:,1], axis=[1,2])/batch_size
    sharp_drag_x = tf.reduce_sum(sharp_force[:,:,:,0], axis=[1,2])/batch_size
    sharp_drag_y = tf.reduce_sum(sharp_force[:,:,:,1], axis=[1,2])/batch_size
    
    drag_lift_ratio = (drag_x/drag_y)
    sharp_drag_lift_ratio = (sharp_drag_x/sharp_drag_y)

    # loss
    loss = -tf.reduce_sum(drag_lift_ratio)

    # init graph
    init = tf.global_variables_initializer()

    # Restore the moving average version of the learned variables for eval.
    variables_to_restore = tf.all_variables()
    variables_to_restore_boundary = [variable for i, variable in enumerate(variables_to_restore) if "boundary_network" in variable.name[:variable.name.index(':')]]
    variables_to_restore_flow = [variable for i, variable in enumerate(variables_to_restore) if "flow_network" in variable.name[:variable.name.index(':')]]
    saver_boundary = tf.train.Saver(variables_to_restore_boundary)
    saver_flow = tf.train.Saver(variables_to_restore_flow)

    # start ses and init
    sess = tf.Session()
    sess.run(init)
    ckpt_boundary = tf.train.get_checkpoint_state(BOUNDARY_DIR)
    ckpt_flow = tf.train.get_checkpoint_state(FLOW_DIR)
    saver_boundary.restore(sess, ckpt_boundary.model_checkpoint_path)
    saver_flow.restore(sess, ckpt_flow.model_checkpoint_path)
    
    graph_def = tf.get_default_graph().as_graph_def(add_shapes=True)

    params_np = (np.random.rand(1,FLAGS.nr_boundary_params) - .5)
 
    sess.run(params_op_init, feed_dict={params_op_set: params_np})
    run_time = FLAGS.boundary_learn_steps

    # make store vectors for values
    plot_error = np.zeros((run_time))
    plot_drag_y = np.zeros((run_time))
    plot_drag_x = np.zeros((run_time))

    # make store dir
    os.system("mkdir ./figs/boundary_learn_image_store")

    # simulated annealing params
    temp = 0.1
    param_old = params_np 
    param_new = distort_param(params_np, std)
    fittness_old = sess.run(loss)
    fittness_new = 0.0

    for i in tqdm(xrange(run_time)):
      sess.run(params_op_init, feed_dict={params_op_set: param_new})
      fittness_new = sess.run(loss)
      print(fittness_new)
      print(fittness_old)
      param_old, fittness_old, temp = simulated_annealing_step(param_old, fittness_old, param_new, fittness_new, temp=temp)
      print(temp)
      param_new = distort_param(param_old, std)

      l, d_y, d_x, p_o = sess.run([loss, sharp_drag_y, sharp_drag_x, params_op], feed_dict={})
      plot_error[i] = np.sum(l)
      plot_drag_x[i] = np.sum(d_x[2])
      plot_drag_y[i] = np.sum(d_y[2])
      if (i+1) % 400 == 0:
        # make video with opencv
        velocity_norm_g, boundary_g = sess.run([predicted_sharp_flow, sharp_boundary],feed_dict={})
        d_y, d_x, l_c, p_o = sess.run([sharp_drag_y, sharp_drag_x, sharp_drag_lift_ratio, params_op], feed_dict={})
        #velocity_norm_g, boundary_g = sess.run([force, boundary],feed_dict={})
        #sflow_plot = np.concatenate([ 5.0*velocity_norm_g[0], boundary_g[0]], axis=1)
        #sflow_plot = np.uint8(grey_to_short_rainbow(sflow_plot))
        #sflow_plot = cv2.applyColorMap(sflow_plot
        #video.write(sflow_plot)
    
        # save plot image to make video
        velocity_norm_g = velocity_norm_g[2,:,:,2]
        boundary_g = boundary_g[2,:,:,0]
        fig = plt.figure()
        fig.set_size_inches(15.5, 7.5)
        a = fig.add_subplot(1,5,1)
        plt.imshow(velocity_norm_g)
        a = fig.add_subplot(1,5,2)
        plt.imshow(boundary_g)
        a = fig.add_subplot(1,5,3)
        plt.plot(plot_error, label="lift/drag")
        plt.xlabel("step")
        plt.legend()
        a = fig.add_subplot(1,5,4)
        plt.plot(plot_drag_x, label="drag_x")
        plt.plot(plot_drag_y, label="drag_y")
        plt.xlabel("step")
        plt.legend()
        a = fig.add_subplot(1,5,5)
        plt.plot(set_params[:,0], l_c, 'bo', label="lift/drag")
        plt.xlabel("angle of attack")
        plt.xlim(min(set_params[:,0])-0.03, max(set_params[:,0])+0.03)
        #plt.legend()
        plt.suptitle("Using Gradient Decent")
        plt.savefig("./figs/boundary_learn_image_store/plot_" + str(i).zfill(5) + ".png")
        if run_time - i <= 100:
          plt.savefig("./figs/" + FLAGS.boundary_learn_loss + "_plot.png")
          #plt.show()
        plt.close(fig)

    # close cv video
    video.release()
    cv2.destroyAllWindows()

    # generate video of plots
    os.system("rm ./figs/" + FLAGS.boundary_learn_loss + "_plot_video.mp4")
    os.system("cat ./figs/boundary_learn_image_store/*.png | ffmpeg -f image2pipe -r 30 -vcodec png -i - -vcodec libx264 ./figs/" + FLAGS.boundary_learn_loss + "_plot_video.mp4")
    os.system("rm -r ./figs/boundary_learn_image_store")

def main(argv=None):  # pylint: disable=unused-argument
  evaluate()

if __name__ == '__main__':
  tf.app.run()

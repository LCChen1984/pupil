import os
import cv2
import numpy as np
from gl_utils import draw_gl_polyline,adjust_gl_view,clear_gl_screen,draw_gl_point,draw_gl_point_norm,basic_gl_setup
from methods import normalize
import atb
import audio
from ctypes import c_int,c_bool
import OpenGL.GL as gl
from OpenGL.GLU import gluOrtho2D

from glfw import *
from plugin import Plugin
#logging
import logging
logger = logging.getLogger(__name__)


# window calbacks
def on_resize(window,w, h):
    active_window = glfwGetCurrentContext()
    glfwMakeContextCurrent(window)
    adjust_gl_view(w,h)
    glfwMakeContextCurrent(active_window)

class Marker_Detector(Plugin):
    """docstring

    """
    def __init__(self,g_pool,atb_pos=(0,0)):
        Plugin.__init__(self)

        self.rects = []

        self.aperture = c_int(9)
        self.window_should_open = False
        self.window_should_close = False
        self._window = None
        self.fullscreen = c_bool(0)
        self.monitor_idx = c_int(0)
        self.monitor_handles = glfwGetMonitors()
        self.monitor_names = [glfwGetMonitorName(m) for m in self.monitor_handles]
        monitor_enum = atb.enum("Monitor",dict(((key,val) for val,key in enumerate(self.monitor_names))))
        #primary_monitor = glfwGetPrimaryMonitor()

        atb_label = "marker Detection"
        # Creating an ATB Bar is required. Show at least some info about the Ref_Detector
        self._bar = atb.Bar(name =self.__class__.__name__, label=atb_label,
            help="marker detection parameters", color=(50, 50, 50), alpha=100,
            text='light', position=atb_pos,refresh=.3, size=(300, 100))
        self._bar.add_var("monitor",self.monitor_idx, vtype=monitor_enum)
        self._bar.add_var("fullscreen", self.fullscreen)
        self._bar.add_var("edge apature",self.aperture, step=2,min=3)
        self._bar.add_button("  open Window   ", self.do_open, key='c')

    def do_open(self):
        if not self._window:
            self.window_should_open = True

    def advance(self):
        pass

    def open_window(self):
        if not self._window:
            if self.fullscreen.value:
                monitor = self.monitor_handles[self.monitor_idx.value]
                mode = glfwGetVideoMode(monitor)
                height,width= mode[0],mode[1]
            else:
                monitor = None
                height,width= 1280,720

            self._window = glfwCreateWindow(height, width, "Calibration", monitor=monitor, share=glfwGetCurrentContext())
            if not self.fullscreen.value:
                glfwSetWindowPos(self._window,200,0)

            on_resize(self._window,height,width)

            #Register callbacks
            glfwSetWindowSizeCallback(self._window,on_resize)
            glfwSetKeyCallback(self._window,self.on_key)
            glfwSetWindowCloseCallback(self._window,self.on_close)


            # gl_state settings
            active_window = glfwGetCurrentContext()
            glfwMakeContextCurrent(self._window)
            basic_gl_setup()
            glfwMakeContextCurrent(active_window)

            self.window_should_open = False


    def on_key(self,window, key, scancode, action, mods):
        if not atb.TwEventKeyboardGLFW(key,int(action == GLFW_PRESS)):
            if action == GLFW_PRESS:
                if key == GLFW_KEY_ESCAPE:
                    self.on_close()


    def on_close(self,window=None):
        self.window_should_close = True

    def close_window(self):
        if self._window:
            glfwDestroyWindow(self._window)
            self._window = None
            self.window_should_close = False


    def update(self,frame,recent_pupil_positions):
        img = frame.img
        gray_img = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
        # self.candidate_points = self.detector.detect(s_img)

        # get threshold image used to get crisp-clean edges
        edges = cv2.adaptiveThreshold(gray_img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, self.aperture.value, 9)
        # cv2.flip(edges,1 ,dst = edges,)
        # display the image for debugging purpuses
        # img[:] = cv2.cvtColor(edges,cv2.COLOR_GRAY2BGR)
         # from edges to contours to ellipses CV_RETR_CCsOMP ls fr hole
        contours, hierarchy = cv2.findContours(edges,
                                        mode=cv2.RETR_TREE,
                                        method=cv2.CHAIN_APPROX_NONE,offset=(0,0)) #TC89_KCOS


        # remove extra encapsulation
        hierarchy = hierarchy[0]
        # turn outmost list into array
        contours =  np.array(contours)
        # keep only contours                        with parents     and      children
        contained_contours = contours[np.logical_and(hierarchy[:,3]>=0, hierarchy[:,2]>=0)]
        # turn on to debug contours
        # cv2.drawContours(img, contours,-1, (0,255,255))
        # cv2.drawContours(img, contained_contours,-1, (0,0,255))
        # aprox_contours = [cv2.approxPolyDP(c,epsilon=2,closed=True) for c in contained_contours]
        # squares = [c for c in aprox_contours if c.shape[0]==4]
        # cv2.drawContours(img, aprox_contours,-1, (255,0,0))

        # any rectagle will be made of 4 segemnts in its approximation
        # squares = [c for c in contained_contours if cv2.approxPolyDP(c,epsilon=2,closed=True).shape[0]==4]

        # contained_contours = contours #overwrite parent children check

        aprox_contours = [cv2.approxPolyDP(c,epsilon=2.5,closed=True) for c in contained_contours]

        rect_cand = [c for c in aprox_contours if c.shape[0]==4]

        rects = np.array(rect_cand,dtype=np.float32)


        # for r in rects:
        #     cv2.polylines(img,[np.int0(r)],isClosed=True,color=(0,0,200))


        rects_shape = rects.shape
        rects.shape = (-1,2) #flatten for rectsubPix

        # subpixel corner fitting
        # define the criteria to stop and refine the rects
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.001)
        cv2.cornerSubPix(gray_img,rects,(3,3),(-1,-1),criteria)

        rects.shape = rects_shape #back to old layout [[rect],[rect],[rect]...] with rect = [corner,corner,corncer,corner]

        def decode(square_img,grid):
            step = square_img.shape[0]/grid
            start = step/2
            msg = otsu[start::step,start::step]
            # border is: first row, last row, first column, last column
            if msg[0,:].any() or msg[-1:0].any() or msg[:,0].any() or msg[:,-1].any():
                # logger.debug("This is not a valid marker: \n %s" %msg)
                return None
            # strip border to get the message
            msg = msg[1:-1,1:-1]/255

            # B|*|*|W   ^
            # *|*|*|*  / \
            # *|*|*|*   |  UP
            # W|*|*|W   |
            # 0,0 -1,0 -1,-1, 0,-1
            # angles are counter-clockwise rotation
            corners = msg[0,0], msg[-1,0], msg[-1,-1], msg[0,-1]
            if corners == (0,1,1,1):
                angle = 0
            elif corners == (1,0,1,1):
                angle = 270
            elif corners == (1,1,0,1):
                angle = 180
            elif corners == (1,1,1,0):
                angle = 90
            else:
                # logger.debug("This marker does not have valid orientation: \n %s " %msg)
                return None

            msg = np.rot90(msg,angle/90)

            # #this assumes a 6*6 grid marker key is the center 4
            # # B|*|*|W   ^
            # # *|W|B|*  / \
            # # *|B|W|*   |  UP
            # # W|*|*|W   |
            # key = msg[1:3,1:3].flatten().tolist()
            # if key == [1,0,0,1]:
            #     return angle, msg
            # else:
            #     return None

            return angle,msg

        offset = 0
        self.rects = []
        for r in rects:
            # cv2.polylines(img,[np.int0(r)],isClosed=True,color=(100,200,0))
            # y_slice = int(min(r[:,:,0])-1),int(max(r[:,:,0])+1)
            # x_slice = int(min(r[:,:,1])-1),int(max(r[:,:,1])+1)
            # marker_img = img[slice(*x_slice),slice(*y_slice)]
            size = 120 # should be a multiple of marker grid
            M = cv2.getPerspectiveTransform(r,np.array(((0.,0.),(0.,size),(size,size),(size,0.)),dtype=np.float32) )
            flat_marker_img =  cv2.warpPerspective(gray_img, M, (size,size) )#[, dst[, flags[, borderMode[, borderValue]]]])

            # Otsu documentation here :
            # https://opencv-python-tutroals.readthedocs.org/en/latest/py_tutorials/py_imgproc/py_thresholding/py_thresholding.html#thresholding
            _ , otsu = cv2.threshold(flat_marker_img,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)


            # cosmetics -- getting a cleaner display of the rectangle marker
            kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (5,5))
            cv2.erode(otsu,kernel,otsu, iterations=2)
            # kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3,3))
            # cv2.dilate(otsu,kernel,otsu, iterations=1)



            marker = decode(otsu, 6)
            if marker is not None:
                angle,msg = marker
                # roll points such that the marker points correspond with oriented marker
                rot_r = np.roll(r,angle/90,axis=0)
                # this way we get the matrix transform with rotation included
                M = cv2.getPerspectiveTransform(rot_r,np.array(((0.,0.),(0.,size),(size,size),(size,0.)),dtype=np.float32) )
                self.rects.append(r)
                img[0:flat_marker_img.shape[0],offset:flat_marker_img.shape[1]+offset,1] = np.rot90(otsu,angle/90)
                offset += size+10
                if offset+size > img.shape[1]:
                    break

        # img[res[:,3],res[:,2]] =[0,255,0]


        # cv2.drawContours(img, squares,-1, (255,0,0))


        if self.window_should_close:
            self.close_window()

        if self.window_should_open:
            self.open_window()

    def gl_display(self):
        """
        for debugging now
        """

        for r in self.rects:
            r.shape = 4,2 #remove encapsulation
            draw_gl_polyline(r,(0.1,1.,1.,.5))

        if self._window:
            self.gl_display_in_window()

    def gl_display_in_window(self):
        active_window = glfwGetCurrentContext()
        glfwMakeContextCurrent(self._window)

        clear_gl_screen()

        glfwSwapBuffers(self._window)
        glfwMakeContextCurrent(active_window)



    def cleanup(self):
        """gets called when the plugin get terminated.
        This happends either volunatily or forced.
        if you have an atb bar or glfw window destroy it here.
        """
        if self._window:
            self.close_window()
        self._bar.destroy()


# shared helper functions for detectors private to the module
def _calibrate_camera(img_pts, obj_pts, img_size):
    # generate pattern size
    camera_matrix = np.zeros((3,3))
    dist_coef = np.zeros(4)
    rms, camera_matrix, dist_coefs, rvecs, tvecs = cv2.calibrateCamera(obj_pts, img_pts,
                                                    img_size, camera_matrix, dist_coef)
    return camera_matrix, dist_coefs

def _gen_pattern_grid(size=(4,11)):
    pattern_grid = []
    for i in xrange(size[1]):
        for j in xrange(size[0]):
            pattern_grid.append([(2*j)+i%2,i,0])
    return np.asarray(pattern_grid, dtype='f4')


def _make_grid(dim=(11,4)):
    """
    this function generates the structure for an assymetrical circle grid
    centerd around 0 width=1, height scaled accordingly
    """
    x,y = range(dim[0]),range(dim[1])
    p = np.array([[[s,i] for s in x] for i in y], dtype=np.float32)
    p[:,1::2,1] += 0.5
    p = np.reshape(p, (-1,2), 'F')

    # scale height = 1
    x_scale =  1./(np.amax(p[:,0])-np.amin(p[:,0]))
    y_scale =  1./(np.amax(p[:,1])-np.amin(p[:,1]))

    p *=x_scale,x_scale/.5

    # center x,y around (0,0)
    x_offset = (np.amax(p[:,0])-np.amin(p[:,0]))/2.
    y_offset = (np.amax(p[:,1])-np.amin(p[:,1]))/2.
    p -= x_offset,y_offset
    return p



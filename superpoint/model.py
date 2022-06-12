# -*-coding:utf8-*-
from turtle import forward
import torch
import torch.nn.functional as F
import numpy as np
from utils.tensor_op import pixel_shuffle
import cv2
import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

class SuperPointNet(torch.nn.Module):
    """
    The magicleap definition of SuperPoint Network.
    Mainly for debug or export homography adaptations
    """
    def __init__(self, input_channel=1, grid_size=8):
        super(SuperPointNet, self).__init__()

        self.grid_size = grid_size

        self.relu = torch.nn.ReLU(inplace=True)
        self.pool = torch.nn.MaxPool2d(kernel_size=2, stride=2)
        c1, c2, c3, c4, c5, d1 = 64, 64, 128, 128, 256, 256
        # Shared Encoder.
        self.conv1a = torch.nn.Conv2d(input_channel, c1, kernel_size=3, stride=1, padding=1)
        self.conv1b = torch.nn.Conv2d(c1, c1, kernel_size=3, stride=1, padding=1)
        self.conv2a = torch.nn.Conv2d(c1, c2, kernel_size=3, stride=1, padding=1)
        self.conv2b = torch.nn.Conv2d(c2, c2, kernel_size=3, stride=1, padding=1)
        self.conv3a = torch.nn.Conv2d(c2, c3, kernel_size=3, stride=1, padding=1)
        self.conv3b = torch.nn.Conv2d(c3, c3, kernel_size=3, stride=1, padding=1)
        self.conv4a = torch.nn.Conv2d(c3, c4, kernel_size=3, stride=1, padding=1)
        self.conv4b = torch.nn.Conv2d(c4, c4, kernel_size=3, stride=1, padding=1)
        # Detector Head.
        self.convPa = torch.nn.Conv2d(c4, c5, kernel_size=3, stride=1, padding=1)
        self.convPb = torch.nn.Conv2d(c5, 65, kernel_size=1, stride=1, padding=0)
        # Descriptor Head.
        self.convDa = torch.nn.Conv2d(c4, c5, kernel_size=3, stride=1, padding=1)
        self.convDb = torch.nn.Conv2d(c5, d1, kernel_size=1, stride=1, padding=0)
        #
        self.softmax = torch.nn.Softmax(dim=1)

        self.load_pretrained_layers()

        

    def forward(self, x):
        """ Forward pass that jointly computes unprocessed point and descriptor
        tensors.
        Input
          x: Image pytorch tensor shaped N x 1 x H x W.
        Output
          semi: Output point pytorch tensor shaped N x 65 x H/8 x W/8.
          desc: Output descriptor pytorch tensor shaped N x 256 x H/8 x W/8.
        """
        if isinstance(x, dict):
            x = x['img']

        # Shared Encoder.
        x = self.relu(self.conv1a(x))
        x = self.relu(self.conv1b(x))
        x = self.pool(x)
        x = self.relu(self.conv2a(x))
        x = self.relu(self.conv2b(x))
        x = self.pool(x)
        x = self.relu(self.conv3a(x))
        x = self.relu(self.conv3b(x))
        x = self.pool(x)
        x = self.relu(self.conv4a(x))
        x = self.relu(self.conv4b(x))
        

        # Detector Head.
        cPa = self.relu(self.convPa(x))
        semi = self.convPb(cPa)
        #
        prob = self.softmax(semi)
        prob = prob[:, :-1, :, :]  # remove dustbin,[B,64,H,W]
        # Reshape to get full resolution heatmap.
        prob = pixel_shuffle(prob, self.grid_size)  # [B,1,H*8,W*8]
        prob = prob.squeeze(dim=1)#[B,H,W]

        # Descriptor Head, useless for export image key points
        cDa = self.relu(self.convDa(x))
        out = self.convDb(cDa)
        dn = torch.norm(out, p=2, dim=1)  # Compute the norm.
        desc_raw = out.div(torch.unsqueeze(dn, 1))  # Divide by norm to normalize.
        ##
        # # interpolation
        desc = F.interpolate(desc_raw, scale_factor=self.grid_size, mode='bilinear', align_corners=False)
        desc = F.normalize(desc, p=2, dim=1)  # normalize by channel

        # prob = {'logits':semi, 'prob':prob}
        # desc = {'desc_raw':desc_raw, 'desc':desc}
        return prob, desc

    def load_pretrained_layers(self):
        self.load_state_dict(torch.load('./superpoint_v1.pth'))

        print("\nLoaded superpoint model.\n")


class AuxiliaryConvolutions(torch.nn.Module):
    """
    Additional convolutions layers
    """

    def __init__(self):
        super(AuxiliaryConvolutions, self).__init__()

        self.relu = torch.nn.ReLU(inplace=True)
        self.pool = torch.nn.MaxPool2d(kernel_size=2, stride=2)

        self.conv5_1 = torch.nn.Conv2d(256, 256, kernel_size=3, padding=1)
        self.conv5_2 = torch.nn.Conv2d(256, 256, kernel_size=3, padding=1)

        self.conv6_1 = torch.nn.Conv2d(256, 128, kernel_size=3, padding=1)
        self.conv6_2 = torch.nn.Conv2d(128, 128, kernel_size=3, padding=1)        
        self.conv6_3 = torch.nn.Conv2d(128, 128, kernel_size=3, padding=1)

        self.fc1 = torch.nn.Linear(60 * 80 * 128, 128)
        self.fc2 = torch.nn.Linear(128, 64)
        self.fc3 = torch.nn.Linear(64, 32)
        self.fc4 = torch.nn.Linear(32, 5)

        self.softmax = torch.nn.Softmax(dim=1)

    def forward(self, desc):
        print(desc.shape)
        x = self.relu(self.conv5_1(desc))
        x = self.relu(self.conv5_2(x))
        x = self.pool(x)
        
        x = self.relu(self.conv6_1(x))
        x = self.relu(self.conv6_2(x))
        x = self.relu(self.conv6_3(x))
        x = self.pool(x)
        
        x = torch.flatten(x,1)

        x = self.fc1(x)
        x = self.fc2(x)
        x = self.fc3(x)
        x = self.fc4(x)

        x = self.softmax(x)

        return x


class SP_Classifier(torch.nn.Module):
    def __init__(self):
        super(SP_Classifier, self).__init__()

        self.sp = SuperPointNet()
        self.aux_convs = AuxiliaryConvolutions()
    
    def forward(self, image):
        prob, desc = self.sp(image)
        class_score = self.aux_convs(desc)

        return class_score



if __name__ == "__main__":
   
    x = torch.randn((2, 1, 240, 320))  
     
    model = SP_Classifier()

    out = model(x)

    print(out)
    print("Success!")

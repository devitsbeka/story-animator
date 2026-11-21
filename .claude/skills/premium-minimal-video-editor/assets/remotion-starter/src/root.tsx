import React from 'react';
import {Composition} from 'remotion';
import {Main} from './scenes';
import {FPS,WIDTH,HEIGHT,DURATION} from './data';
export const Root:React.FC=()=> <Composition id="PremiumMinimal" component={Main} durationInFrames={DURATION} fps={FPS} width={WIDTH} height={HEIGHT}/>;

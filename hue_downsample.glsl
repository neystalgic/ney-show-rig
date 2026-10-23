// HUE RIG -- shrinks the picture to 64 x 40 by averaging blocks of it, so the
// engine can read lamp colours cheaply. Input 0 = any picture.
layout(location = 0) out vec4 fragColor;
void main()
{
    vec2 inRes  = vec2(textureSize(sTD2DInputs[0], 0));
    vec2 outRes = uTDOutputInfo.res.zw;
    vec2 cell   = 1.0 / outRes;                       // this pixel's footprint (0-1)
    vec4 sum    = vec4(0.0);
    for (int j = 0; j < 4; j++)
    for (int i = 0; i < 4; i++)
        sum += texture(sTD2DInputs[0], vUV.st + cell * (vec2(float(i), float(j)) + 0.5) / 4.0 - cell * 0.5);
    fragColor = TDOutputSwizzle(sum / 16.0);
}
